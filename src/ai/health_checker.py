"""健康检查与熔断 - APScheduler 定时探测 + 状态机."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.policy_snapshot import RoutingPolicySnapshot
from src.db.models import AiSource
from src.db.session import session_scope
from src.utils.logger import get_logger


class HealthChecker:
    """AI 源健康检查与熔断管理.

    状态机：健康→探测中→降级→熔断→冷却恢复
    """

    def __init__(self, policy: RoutingPolicySnapshot) -> None:
        # policy 必须是纯数据快照：本对象长期持有，跨会话存活
        self.policy = policy
        self.logger = get_logger()
        self._task: asyncio.Task | None = None

    async def check_all(self, session: AsyncSession) -> None:
        """对所有 enabled 源发起健康探测.

        历史实现是把所有源的探测包在一个大事务里，最后一次性 commit——
        单源探测 5–30s × N 个源 = 写锁窗口 N×数十秒，期间所有其它写（网关计数器、
        AI 调用日志）的 busy_timeout 全部撞穿，日志里表现为偶发的
        “AI源计数器写回失败 / AI调用日志落库失败 database is locked”。

        现改为：
        - 先把 enabled 源列表读出来并立刻 commit（释放读事务）
        - 每个源探测 + 写回用独立 session_scope 包裹，写完立刻 commit 释放写锁
        - 单源写回失败仅告警，不影响其它源
        """
        from src.ai.model_adapter import get_model_adapter

        stmt = select(AiSource).where(AiSource.enabled == True)
        result = await session.execute(stmt)
        sources = list(result.scalars().all())
        # 读快照立刻提交，不携带任何行锁进入下面子事务
        await session.commit()

        adapter = get_model_adapter()
        for source in sources:
            await self._check_one(source, adapter)

    async def _check_one(self, source: AiSource, adapter: Any) -> None:
        """单源独立健康探测与状态写回.

        每个源在独立短事务中完成探测与写回，最大单源写锁窗口 = 网络 RTT，
        不会阻塞网关计数器 / AI 调用日志等其它写操作。
        """
        try:
            ok = await adapter.health_check(source)
        except Exception as e:
            self.logger.error(f"健康检查异常 {source.name}: {e}")
            ok = False

        try:
            async with session_scope() as sub_session:
                fresh = await sub_session.get(AiSource, source.source_id)
                if fresh is None:
                    return
                now = datetime.now(timezone.utc)
                fresh.last_check_at = now
                if ok:
                    if fresh.health_status in ("circuit_broken", "degraded", "unhealthy"):
                        fresh.health_status = "healthy"
                        fresh.fail_count = 0
                        self.logger.info(f"AI源 {fresh.name} 恢复健康")
                    fresh.success_count += 1
                else:
                    fresh.fail_count += 1
                    if fresh.health_status == "healthy":
                        fresh.health_status = "degraded"
                    elif fresh.health_status == "degraded":
                        if fresh.fail_count >= self.policy.circuit_break_threshold:
                            fresh.health_status = "circuit_broken"
                            fresh.circuit_broken_until = now + timedelta(
                                seconds=self.policy.circuit_break_cool_seconds
                            )
                            self.logger.warning(f"AI源 {fresh.name} 触发熔断")
        except Exception as e:
            # 单源写回失败仅告警，绝不中断其它源
            self.logger.error(f"健康检查写回失败 {source.name}: {e}")

    def is_available(self, source: AiSource) -> bool:
        """判断源是否可路由."""
        if not source.enabled:
            return False
        if source.health_status == "circuit_broken":
            if source.circuit_broken_until:
                now = datetime.now(timezone.utc)
                if now < source.circuit_broken_until:
                    return False
        return source.health_status in ("healthy", "degraded", "unknown")

    def get_weight(self, source: AiSource) -> float:
        """获取路由权重（降级源权重降低）."""
        if source.health_status == "degraded":
            return source.weight * 0.1
        return float(source.weight)

    async def start_periodic(self) -> None:
        """启动周期性健康检查."""
        interval = self.policy.health_check_interval_seconds

        async def _loop():
            while True:
                try:
                    async with session_scope() as session:
                        await self.check_all(session)
                except Exception as e:
                    self.logger.error(f"健康检查周期任务异常: {e}")
                await asyncio.sleep(interval)

        self._task = asyncio.create_task(_loop())
        self.logger.info(f"健康检查已启动，间隔 {interval}s")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None