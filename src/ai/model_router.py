"""多模型路由器 - 四种路由策略 + Failover."""
from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.adapters.openai_compatible import OpenAiCompatibleAdapter
from src.ai.health_checker import HealthChecker
from src.ai.model_adapter import get_model_adapter
from src.ai.policy_snapshot import RoutingPolicySnapshot
from src.ai.retry_policy import RetryPolicy, describe_exception
from src.db.models import AiSource
from src.utils.logger import get_logger


class ModelRouter:
    """多模型路由核心.

    支持 manual/failover/load_balance/cost_first 四种策略。
    单源失败自动 Failover 到下一源。
    支持按 scene_key (e.g. ``outline.generate-outline-batch``) 进行任务级源筛选：
    源 tags 含 ``task:<task>`` 表示专门服务于该任务；不含 ``task:*`` 的源视为通用兜底。
    """

    def __init__(
        self, policy: RoutingPolicySnapshot, health_checker: HealthChecker
    ) -> None:
        # policy 必须是纯数据快照：ORM 实例在会话关闭后会游离，
        # 再读属性会抛 DetachedInstanceError（sqlalche.me/e/20/bhk3）
        self.policy = policy
        self.health_checker = health_checker
        self.logger = get_logger()
        self.adapter = get_model_adapter()

    async def load_sources(self, session: AsyncSession) -> list[AiSource]:
        """在短会话内加载启用源；返回的实例随会话关闭而游离，但属性已加载可直接读."""
        stmt = select(AiSource).where(AiSource.enabled == True)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _parse_task_tags(source: AiSource) -> list[str]:
        """从 ai_sources.tags 中解析出 ``task:xxx`` 形式的标签列表."""
        raw = source.tags or ""
        return [
            t[len("task:"):].strip()
            for t in raw.split(",")
            if t.strip().startswith("task:")
        ]

    @staticmethod
    def _source_matches_task(source: AiSource, task: str | None) -> bool:
        """源是否适用于指定 task.

        - 无 task 参数：返回 True（向后兼容，调用方未传入 scene_key 时不筛选）
        - 源没有任何 ``task:*`` 标签：返回 True（通用兜底源适用于全部任务）
        - 源有 ``task:*`` 标签且包含当前 task：返回 True
        - 其它情况：返回 False
        """
        if not task:
            return True
        task_tags = ModelRouter._parse_task_tags(source)
        if not task_tags:
            # 通用兜底源：未声明适用任务，适用于全部任务
            return True
        return task in task_tags

    def _select_candidates(
        self, sources: list[AiSource], scene_key: str | None = None
    ) -> list[AiSource]:
        """按策略选择候选源序列.

        Args:
            sources: 已加载的源列表
            scene_key: 形如 ``module.scene`` 的调用场景标识（如 ``outline.generate-outline-batch``），
                    用于任务级筛选；为 None 时不筛选（向后兼容）
        """
        available = [s for s in sources if self.health_checker.is_available(s)]
        if not available:
            return []

        # 任务级过滤：从 scene_key 拆出 task（即 module 名），筛选出匹配源；
        # 若匹配源为空，**保留全部 available**（避免因筛选导致"无可用源"）。
        task: str | None = None
        if scene_key:
            head = scene_key.split(".", 1)[0].strip()
            if head:
                task = head

        if task:
            matched = [s for s in available if self._source_matches_task(s, task)]
            if matched:
                available = matched
            else:
                # 没有专门匹配源时不抛错，回退到全集（仍能完成调用）
                self.logger.debug(
                    f"任务 {task} 无专属 AI 源，回退到全部可用源（{len(available)} 个）"
                )

        strategy = self.policy.strategy
        if strategy == "manual":
            manual_id = self.policy.manual_source_id
            selected = [s for s in available if s.source_id == manual_id]
            return selected

        elif strategy == "failover":
            return sorted(available, key=lambda s: s.priority)

        elif strategy == "load_balance":
            weighted: list[AiSource] = []
            for s in available:
                w = max(1, int(self.health_checker.get_weight(s) * 10))
                weighted.extend([s] * w)
            random.shuffle(weighted)
            seen: list[AiSource] = []
            for s in weighted:
                if s not in seen:
                    seen.append(s)
            return seen

        elif strategy == "cost_first":
            def cost_key(s: AiSource) -> tuple:
                tags = s.tags or ""
                is_free = "free" in tags or "免费" in tags
                is_local = "local" in tags or "本地" in tags or s.source_type == "local_ollama"
                return (0 if is_free or is_local else 1, s.priority)
            return sorted(available, key=cost_key)

        return available

    async def route_call(
        self,
        sources: list[AiSource],
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
        on_failover: Any = None,
        scene_key: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """路由调用，含 Failover.

        不接收 DB 会话：sources 为已加载属性的就绪实例（可游离），
        HTTP 期间绝不持有任何数据库事务；成功/失败计数先改内存，
        由调用方（AiGateway）在调用结束后用独立短会话写回。

        Args:
            scene_key: 形如 ``module.scene`` 的调用场景，传入 ``_select_candidates``
                    以筛选任务级专属 AI 源；不影响后续重试与 failover 流程。

        Returns:
            包含 content、source_id、source_name、model_name、failover_from 的结果

        Raises:
            RuntimeError: 所有源均失败
        """
        candidates = self._select_candidates(sources, scene_key=scene_key)
        if not candidates:
            raise RuntimeError("无可用 AI 源，请检查配置")

        failover_from: str | None = None
        last_exc: Exception | None = None

        for source in candidates:
            retry = RetryPolicy(max_retries=source.max_retries)
            try:
                result = await retry.execute(
                    self.adapter.call,
                    source=source,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra,
                )
                result["source_id"] = source.source_id
                result["source_name"] = source.name
                result["model_name"] = source.model_name
                result["failover_from"] = failover_from
                source.success_count += 1
                if source.health_status in ("degraded", "circuit_broken", "unknown", "unhealthy"):
                    if source.success_count >= 5:
                        source.health_status = "healthy"
                        source.fail_count = 0
                return result
            except Exception as e:
                last_exc = e
                source.fail_count += 1
                if source.health_status == "healthy":
                    source.health_status = "degraded"
                self.logger.info(
                    f"AI源 {source.name} 调用失败，尝试故障转移: {describe_exception(e)}"
                )
                if failover_from is None:
                    failover_from = source.source_id
                else:
                    failover_from = f"{failover_from}->{source.source_id}"
                if on_failover:
                    on_failover(source, e)
                if not self.policy.failover_within_retry:
                    break

        # 带上异常类型：超时类异常的 str() 可能为空，否则界面只能看到"最后错误: "
        detail = describe_exception(last_exc) if last_exc else "无可用 AI 源返回结果"
        raise RuntimeError(f"所有 AI 源均失败，最后错误: {detail}")