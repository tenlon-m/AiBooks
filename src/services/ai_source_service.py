"""AI 源配置服务 - CRUD、密钥加密、路由策略、连通性测试."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.ai_source_schema import (
    AiSourceCreateRequest,
    AiSourceDto,
    AiSourceUpdateRequest,
    RoutingPolicyDto,
    RoutingPolicyRequest,
)
from src.config.crypto import decrypt_secret, encrypt_secret
from src.db.models import AiSource, RoutingPolicy
from src.db.session import release_write_lock
from src.utils.logger import get_logger


class AiSourceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.logger = get_logger()

    @staticmethod
    def _split_tags(tags_str: str | None) -> tuple[list[str], list[str]]:
        """把 ai_sources.tags 字段拆为 (展示标签, 任务标签).

        约定：以 ``task:`` 前缀的 tag 视为任务标签，存为 ``task:outline`` / ``task:writing``；
        其余视为展示标签（如 "免费"/"中文"）。
        无 ``task:`` 前缀的源被视为通用兜底源（适用于全部任务）。
        """
        if not tags_str:
            return [], []
        display: list[str] = []
        task: list[str] = []
        for raw in tags_str.split(","):
            t = raw.strip()
            if not t:
                continue
            if t.startswith("task:"):
                name = t[len("task:") :].strip()
                if name and name not in task:
                    task.append(name)
            else:
                if t not in display:
                    display.append(t)
        return display, task

    @staticmethod
    def _join_tags(display_tags: list[str], task_tags: list[str]) -> str:
        """把 (展示标签, 任务标签) 合并回 ai_sources.tags 字段字符串.

        防御：调用方传入 ``task:outline`` 时也会被归一化为 ``outline``，
        避免出现 ``task:task:outline`` 这种双重前缀。
        """
        items: list[str] = []
        seen: set[str] = set()
        for t in display_tags or []:
            s = str(t).strip()
            if s and s not in seen:
                items.append(s)
                seen.add(s)
        for t in task_tags or []:
            s = str(t).strip()
            if not s:
                continue
            # 归一化：去掉可能的 task: 前缀，避免嵌套
            if s.startswith("task:"):
                s = s[len("task:") :].strip()
                if not s:
                    continue
            prefixed = f"task:{s}"
            if prefixed not in seen:
                items.append(prefixed)
                seen.add(prefixed)
        return ",".join(items)

    def _to_dto(self, source: AiSource) -> AiSourceDto:
        display_tags, task_tags = self._split_tags(source.tags)
        return AiSourceDto(
            source_id=source.source_id,
            name=source.name,
            source_type=source.source_type,
            api_endpoint=source.api_endpoint,
            model_name=source.model_name,
            priority=source.priority,
            weight=source.weight,
            enabled=source.enabled,
            health_status=source.health_status,
            last_check_at=source.last_check_at,
            success_count=source.success_count,
            fail_count=source.fail_count,
            tags=display_tags,
            task_tags=task_tags,
        )

    async def create(self, req: AiSourceCreateRequest) -> AiSourceDto:
        existing = await self.session.execute(select(AiSource).where(AiSource.name == req.name))
        if existing.scalars().first():
            raise ValueError(f"AI源名称已存在: {req.name}")
        # 防御：清洗 task_tags，避免出现 "task:xxx" 嵌套前缀
        clean_task_tags = [
            str(t).strip().removeprefix("task:")
            for t in (req.task_tags or [])
            if str(t).strip()
        ]
        merged_tags = self._join_tags(req.tags or [], clean_task_tags)
        source = AiSource(
            source_id=str(uuid.uuid4()),
            name=req.name,
            source_type=req.source_type,
            api_endpoint=req.api_endpoint,
            model_name=req.model_name,
            api_key_enc=encrypt_secret(req.api_key) if req.api_key else None,
            timeout_seconds=req.timeout_seconds,
            max_retries=req.max_retries,
            priority=req.priority,
            weight=req.weight,
            enabled=req.enabled,
            tags=merged_tags,
            health_status="unknown",
        )
        self.session.add(source)
        await self.session.flush()
        return self._to_dto(source)

    async def list_all(self) -> list[AiSourceDto]:
        result = await self.session.execute(select(AiSource))
        return [self._to_dto(s) for s in result.scalars().all()]

    async def get(self, source_id: str) -> AiSourceDto | None:
        source = await self.session.get(AiSource, source_id)
        return self._to_dto(source) if source else None

    async def get_decrypted_key(self, source_id: str) -> str | None:
        """返回解密后的 API Key（供前端查看已保存的密钥）.

        - 源不存在时抛 ValueError（路由层转 404）
        - api_key_enc 为空（如本地 Ollama）返回 None
        - 解密失败抛 ValueError（路由层转 500，提示用户重新填写）
        """
        source = await self.session.get(AiSource, source_id)
        if not source:
            raise ValueError(f"AI源不存在: {source_id}")
        if not source.api_key_enc:
            return None
        try:
            return decrypt_secret(source.api_key_enc)
        except Exception as e:
            self.logger.warning(f"API Key 解密失败 source_id={source_id}: {e}")
            raise ValueError("API Key 解密失败：密钥文件(.secret_key)与数据库不匹配，请重新填写 API Key") from e

    async def update(self, source_id: str, req: AiSourceUpdateRequest) -> AiSourceDto:
        source = await self.session.get(AiSource, source_id)
        if not source:
            raise ValueError(f"AI源不存在: {source_id}")
        for field in ("name", "source_type", "api_endpoint", "model_name", "timeout_seconds", "max_retries", "priority", "weight", "enabled"):
            val = getattr(req, field)
            if val is not None:
                setattr(source, field, val)
        if req.api_key is not None and req.api_key != "":
            source.api_key_enc = encrypt_secret(req.api_key)
        # tags / task_tags 任一变化都需要重算：
        # - tags=None 且 task_tags=None：保留原值
        # - tags=None 且 task_tags=[]：仅清空任务限制
        # - tags=[] 且 task_tags=None：仅清空展示标签
        # - 两者都传：合并后覆盖
        if req.tags is not None or req.task_tags is not None:
            current_display, current_task = self._split_tags(source.tags)
            new_display = req.tags if req.tags is not None else current_display
            if req.task_tags is None:
                new_task = current_task
            else:
                new_task = [
                    str(t).strip().removeprefix("task:")
                    for t in req.task_tags
                    if str(t).strip()
                ]
            source.tags = self._join_tags(new_display, new_task)
        await self.session.flush()
        return self._to_dto(source)

    async def delete(self, source_id: str) -> bool:
        source = await self.session.get(AiSource, source_id)
        if not source:
            return False
        policy = await self.session.execute(select(RoutingPolicy).where(RoutingPolicy.policy_id == "default"))
        rp = policy.scalars().first()
        if rp and rp.manual_source_id == source_id:
            raise ValueError("该源被路由策略引用，请先切换")
        await self.session.delete(source)
        await self.session.flush()
        return True

    async def test_connection(self, source_id: str) -> dict[str, Any]:
        source = await self.session.get(AiSource, source_id)
        if not source:
            raise ValueError(f"AI源不存在: {source_id}")
        import time

        from src.ai.model_adapter import get_model_adapter
        from src.ai.model_profiler import build_model_profile
        from datetime import datetime
        adapter = get_model_adapter()
        model_name = source.model_name

        # 健康探测是网络调用（最长 timeout_seconds）。只要本会话（或调用方）还有
        # 未提交的 DML，写锁就会一直被持有到 commit，期间会阻塞自动保存与网关
        # 计数器写回（database is locked）。探测前先结束事务。
        await release_write_lock(self.session)

        if source.api_key_enc:
            try:
                from src.config.crypto import decrypt_secret

                decrypt_secret(source.api_key_enc)
            except Exception:
                source.health_status = "unhealthy"
                source.last_check_at = datetime.now()
                source.fail_count += 1
                await self.session.flush()
                profile = build_model_profile(model_name, latency_ms=None)
                return {
                    "source_id": source_id,
                    "success": False,
                    "message": "API Key 解密失败：密钥文件(.secret_key)与数据库不匹配，请重新填写 API Key",
                    "latency_ms": 0,
                    "model_profile": profile.to_dict(),
                }
        elif source.source_type == "online_openai_compatible":
            source.health_status = "unhealthy"
            source.last_check_at = datetime.now()
            source.fail_count += 1
            await self.session.flush()
            profile = build_model_profile(model_name, latency_ms=None)
            return {
                "source_id": source_id,
                "success": False,
                "message": "该AI源未配置 API Key，请填写后重试",
                "latency_ms": 0,
                "model_profile": profile.to_dict(),
            }

        start = time.monotonic()
        try:
            ok = await adapter.health_check(source)
            latency_ms = int((time.monotonic() - start) * 1000)
            source.health_status = "healthy" if ok else "unhealthy"
            source.last_check_at = datetime.now()
            if ok:
                source.success_count += 1
            else:
                source.fail_count += 1
            await self.session.flush()
            # 连接成功后附带模型特点档案：辅助用户为该模型配置"适用任务"标签
            profile = build_model_profile(model_name, latency_ms=latency_ms if ok else None)
            return {
                "source_id": source_id,
                "success": ok,
                "message": "连通正常" if ok else "连通失败",
                "latency_ms": latency_ms,
                "model_profile": profile.to_dict(),
            }
        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            source.health_status = "unhealthy"
            source.last_check_at = datetime.now()
            source.fail_count += 1
            await self.session.flush()
            # 连接失败也给出模型特点说明（不带实测延迟），便于用户判断模型是否适配
            profile = build_model_profile(model_name, latency_ms=None)
            return {
                "source_id": source_id,
                "success": False,
                "message": str(e),
                "latency_ms": latency_ms,
                "model_profile": profile.to_dict(),
            }

    async def get_routing_policy(self) -> RoutingPolicyDto:
        result = await self.session.execute(select(RoutingPolicy).where(RoutingPolicy.policy_id == "default"))
        rp = result.scalars().first()
        if rp is None:
            rp = RoutingPolicy(policy_id="default")
            self.session.add(rp)
            await self.session.flush()
        return RoutingPolicyDto(
            policy_id=rp.policy_id,
            strategy=rp.strategy,
            manual_source_id=rp.manual_source_id,
            health_check_interval_seconds=rp.health_check_interval_seconds,
            circuit_break_threshold=rp.circuit_break_threshold,
            circuit_break_cool_seconds=rp.circuit_break_cool_seconds,
            failover_within_retry=rp.failover_within_retry,
        )

    async def update_routing_policy(self, req: RoutingPolicyRequest) -> RoutingPolicyDto:
        result = await self.session.execute(select(RoutingPolicy).where(RoutingPolicy.policy_id == "default"))
        rp = result.scalars().first()
        if rp is None:
            rp = RoutingPolicy(policy_id="default")
            self.session.add(rp)
        rp.strategy = req.strategy
        rp.manual_source_id = req.manual_source_id
        rp.health_check_interval_seconds = req.health_check_interval_seconds
        rp.circuit_break_threshold = req.circuit_break_threshold
        rp.circuit_break_cool_seconds = req.circuit_break_cool_seconds
        rp.failover_within_retry = req.failover_within_retry
        await self.session.flush()
        return await self.get_routing_policy()
    async def get_active_source_display(self) -> dict[str, Any]:
        """按路由策略差异化返回当前活跃AI源的显示文本."""
        policy = await self.get_routing_policy()
        strategy = policy.strategy
        stmt = select(AiSource).where(AiSource.enabled == True)
        result = await self.session.execute(stmt)
        sources = list(result.scalars().all())
        available = [s for s in sources if s.health_status in ("healthy", "unknown", "degraded")]

        if not available:
            return {"display_text": "无可用AI源", "strategy": strategy, "source_count": 0}

        if strategy == "manual":
            manual_id = policy.manual_source_id
            target = next((s for s in available if s.source_id == manual_id), None)
            if target:
                return {"display_text": target.name, "strategy": strategy, "source_count": 1}
            return {"display_text": "未指定手动源", "strategy": strategy, "source_count": 0}

        if strategy == "failover":
            sorted_sources = sorted(available, key=lambda s: s.priority)
            return {"display_text": sorted_sources[0].name, "strategy": strategy, "source_count": len(available)}

        if strategy == "load_balance":
            return {"display_text": f"负载均衡({len(available)}源)", "strategy": strategy, "source_count": len(available)}

        if strategy == "cost_first":
            def cost_key(s: AiSource) -> tuple:
                tags = s.tags or ""
                is_free = "免费" in tags or "free" in tags
                is_local = "本地" in tags or s.source_type == "local_ollama"
                return (0 if is_free or is_local else 1, s.priority)
            sorted_sources = sorted(available, key=cost_key)
            return {"display_text": sorted_sources[0].name, "strategy": strategy, "source_count": len(available)}

        return {"display_text": "未知策略", "strategy": strategy, "source_count": len(available)}
    async def export_all_sources(self) -> dict[str, Any]:
        """导出全部 AI 源配置（剥离 API Key），供跨电脑迁移."""
        result = await self.session.execute(select(AiSource))
        sources = result.scalars().all()
        source_list = []
        for s in sources:
            display_tags, task_tags = self._split_tags(s.tags)
            source_list.append({
                "name": s.name,
                "source_type": s.source_type,
                "api_endpoint": s.api_endpoint,
                "model_name": s.model_name,
                "priority": s.priority,
                "weight": s.weight,
                "enabled": s.enabled,
                "tags": display_tags,
                "task_tags": task_tags,
                "timeout_seconds": s.timeout_seconds,
                "max_retries": s.max_retries,
            })
        rp = await self.get_routing_policy()
        return {"ai_sources": source_list, "routing_policy": rp.model_dump()}

    async def import_sources(self, data: dict[str, Any]) -> dict[str, Any]:
        """导入 AI 源配置（不含 API Key，用户须自行重填）."""
        imported = 0
        skipped = 0
        for item in data.get("ai_sources", []):
            name = item.get("name")
            source_type = item.get("source_type")
            api_endpoint = item.get("api_endpoint")
            model_name = item.get("model_name")
            if not all([name, source_type, api_endpoint, model_name]):
                raise ValueError(
                    f"导入数据缺少必填字段(name/source_type/api_endpoint/model_name): {item}"
                )
            existing = await self.session.execute(
                select(AiSource).where(AiSource.name == name)
            )
            if existing.scalars().first():
                skipped += 1
                continue
            clean_task_tags = [
                str(t).strip().removeprefix("task:")
                for t in (item.get("task_tags") or [])
                if str(t).strip()
            ]
            merged_tags = self._join_tags(item.get("tags") or [], clean_task_tags)
            source = AiSource(
                source_id=str(uuid.uuid4()),
                name=name,
                source_type=source_type,
                api_endpoint=api_endpoint,
                model_name=model_name,
                api_key_enc=None,
                timeout_seconds=item.get("timeout_seconds", 60),
                max_retries=item.get("max_retries", 3),
                priority=item.get("priority", 1),
                weight=item.get("weight", 1),
                enabled=False,
                health_status="unknown",
                tags=merged_tags,
            )
            self.session.add(source)
            imported += 1
        await self.session.flush()

        rp_data = data.get("routing_policy")
        if rp_data and isinstance(rp_data, dict):
            rp_result = await self.session.execute(
                select(RoutingPolicy).where(RoutingPolicy.policy_id == "default")
            )
            rp = rp_result.scalars().first()
            if rp is None:
                rp = RoutingPolicy(policy_id="default")
                self.session.add(rp)
            rp.strategy = rp_data.get("strategy", "failover")
            rp.manual_source_id = None
            rp.health_check_interval_seconds = rp_data.get("health_check_interval_seconds", 30)
            rp.circuit_break_threshold = rp_data.get("circuit_break_threshold", 3)
            rp.circuit_break_cool_seconds = rp_data.get("circuit_break_cool_seconds", 60)
            rp.failover_within_retry = rp_data.get("failover_within_retry", True)
            await self.session.flush()

        return {"imported": imported, "skipped": skipped}