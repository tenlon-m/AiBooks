"""AI 网关统一入口 - 所有 AI 调用的唯一出口.

流程：接收 (scene, params) → PromptBuilder 渲染 → ModelRouter 路由 → ModelAdapter 调用 → RetryPolicy 重试 → CallLogger 落库 → 返回结果
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.call_logger import CallLogger
from src.ai.health_checker import HealthChecker
from src.ai.model_router import ModelRouter
from src.ai.policy_snapshot import RoutingPolicySnapshot
from src.ai.prompt_builder import get_prompt_builder
from src.ai.retry_policy import describe_exception
from src.db.lock_diagnostics import report_lock_failure
from src.db.models import AiSource, RoutingPolicy
from src.db.session import get_session_factory
from src.utils.logger import get_logger


class AiGateway:
    """AI 网关统一入口.

    业务模块仅通过 AiGateway 调用 AI，禁止直接发起 HTTP 请求。
    """

    def __init__(self) -> None:
        self.logger = get_logger()
        self.prompt_builder = get_prompt_builder()
        self._router: ModelRouter | None = None
        self._health_checker: HealthChecker | None = None
        self._policy_snapshot: RoutingPolicySnapshot | None = None

    async def _ensure_router(self, session: AsyncSession) -> ModelRouter:
        """取路由器；路由策略以纯数据快照传入（快照变化时重建）.

        注意：绝不能把 RoutingPolicy ORM 实例交给路由器长期缓存——本网关是
        单例，该实例绑定在本次会话上，会话 commit/close 后属性过期、实例游离，
        下一次调用再读 policy.strategy 即抛 DetachedInstanceError
        （https://sqlalche.me/e/20/bhk3），表现为"分批生成第二批必失败 502"。
        """
        from sqlalchemy import select

        stmt = select(RoutingPolicy).where(RoutingPolicy.policy_id == "default")
        result = await session.execute(stmt)
        policy = result.scalars().first()
        if policy is None:
            policy = RoutingPolicy(
                policy_id="default",
                strategy="failover",
                health_check_interval_seconds=30,
                circuit_break_threshold=3,
                circuit_break_cool_seconds=60,
                failover_within_retry=True,
            )
            session.add(policy)
            await session.flush()
        snapshot = RoutingPolicySnapshot.from_model(policy)
        if self._router is None or snapshot != self._policy_snapshot:
            self._health_checker = HealthChecker(snapshot)
            self._router = ModelRouter(snapshot, self._health_checker)
            self._policy_snapshot = snapshot
        return self._router

    async def call(
        self,
        module: str,
        scene: str,
        params: dict[str, Any],
        project_id: str | None = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
        system_prompt: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """统一 AI 调用入口.

        Args:
            module: 提示词模块名
            scene: 提示词场景名
            params: 模板参数
            project_id: 项目ID（用于日志）
            temperature: 温度参数
            max_tokens: 最大token
            system_prompt: 系统提示词（可选，默认由模板生成）
            extra: 额外传递给模型的参数

        Returns:
            包含 content、source_id、source_name、model_name 等的结果字典
        """
        prompt = self.prompt_builder.build(module, scene, params)
        start = time.monotonic()
        scene_key = f"{module}.{scene}"
        result: dict[str, Any] | None = None
        failure: Exception | None = None

        # 三段式，保证 AI HTTP 调用期间不持有任何数据库事务：
        # 此前一个会话横跨数分钟的 HTTP 调用，期间其它写入（日志落库/健康检查/
        # 计数器更新）与本会话的 UPDATE ai_sources 撞锁，抛 database is locked，
        # 把本已成功的 AI 调用整体判为失败（界面表现为分批生成 502）。
        # 1) 短会话：读路由策略与 AI 源（会话随即关闭，实例游离但属性已加载）
        sources: list[Any] = []
        counters_before: dict[str, tuple[Any, Any, Any]] = {}
        try:
            async with get_session_factory()() as session:
                router = await self._ensure_router(session)
                sources = await router.load_sources(session)
                await session.commit()
        except Exception as e:
            failure = e

        # 2) 无 DB 事务：执行 AI 调用（含重试与 Failover），计数先落内存
        if failure is None:
            counters_before = {
                s.source_id: (s.success_count, s.fail_count, s.health_status)
                for s in sources
            }
            try:
                result = await router.route_call(
                    sources=sources,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    scene_key=scene_key,
                    **extra,
                )
            except Exception as e:
                failure = e

        # 3) 短会话：把内存中的计数/健康状态变化写回（可重试，失败仅告警）
        if sources:
            await self._apply_source_updates(sources, counters_before)

        duration_ms = int((time.monotonic() - start) * 1000)

        if failure is not None:
            await self._log_call(
                scene=scene_key,
                prompt=prompt,
                response="",
                duration_ms=duration_ms,
                status="failed",
                source_id=None,
                source_name=None,
                model_name=None,
                failover_from=None,
                project_id=project_id,
            )
            raise failure

        assert result is not None
        await self._log_call(
            scene=scene_key,
            prompt=prompt,
            response=result.get("content", ""),
            duration_ms=duration_ms,
            status="success",
            source_id=result.get("source_id"),
            source_name=result.get("source_name"),
            model_name=result.get("model_name"),
            failover_from=result.get("failover_from"),
            project_id=project_id,
        )
        from src.ai.source_notifier import notify_source_call
        notify_source_call(
            result.get("source_name", "未知"),
            result.get("failover_from"),
            module,
            scene,
        )
        return result

    async def _apply_source_updates(
        self,
        sources: list[Any],
        counters_before: dict[str, tuple[Any, Any, Any]],
    ) -> None:
        """把路由期间的源计数/健康状态变化写回数据库.

        计数器仅是遥测数据：写回失败绝不影响业务调用结果。
        日志方面：普通错误记 WARNING；若为 SQLite 锁冲突则记 ERROR 并附上
        "当前谁持有写锁"的诊断上下文（见 ``src/db/lock_diagnostics``）——
        本方法几乎只会被别人长时间持有写锁拖垮，症状本身没有排障价值。
        """
        from sqlalchemy import update

        changed = [
            s
            for s in sources
            if (s.success_count, s.fail_count, s.health_status)
            != counters_before.get(s.source_id)
        ]
        if not changed:
            return
        last_error: Exception | None = None
        # 6 次重试 + busy_timeout=60s，下限约 6×60 + (1+2+4+8+13+21)= 408s，
        # 覆盖健康检查等多源串行写造成的最长锁窗口
        for attempt in range(6):
            try:
                async with get_session_factory()() as session:
                    for s in changed:
                        await session.execute(
                            update(AiSource)
                            .where(AiSource.source_id == s.source_id)
                            .values(
                                health_status=s.health_status,
                                success_count=s.success_count,
                                fail_count=s.fail_count,
                            )
                        )
                    await session.commit()
                return
            except Exception as e:
                last_error = e
                await asyncio.sleep(1.0 + attempt * 2)
        # 锁冲突时升级为 ERROR 并附上"谁攥着写锁"：本方法的失败几乎总是被别人
        # 长时间持有写锁拖垮的，只报症状会让排障变成猜谜。
        report_lock_failure(
            self.logger,
            "AI源计数器写回",
            last_error,
            detail=describe_exception(last_error),
        )

    async def _log_call(
        self,
        scene: str,
        prompt: str,
        response: str,
        duration_ms: int,
        status: str,
        source_id: str | None,
        source_name: str | None,
        model_name: str | None,
        failover_from: str | None,
        project_id: str | None,
    ) -> None:
        """AI 调用日志落库 - 独立会话 + 短重试，失败绝不影响业务调用结果.

        锁冲突时记 ERROR + 写锁持有者上下文，普通错误记 WARNING。
        """
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                async with get_session_factory()() as log_session:
                    await CallLogger(log_session).log(
                        scene=scene,
                        prompt=prompt,
                        response=response,
                        duration_ms=duration_ms,
                        status=status,
                        source_id=source_id,
                        source_name=source_name,
                        model_name=model_name,
                        failover_from=failover_from,
                        project_id=project_id,
                    )
                    await log_session.commit()
                return
            except Exception as e:
                last_error = e
                await asyncio.sleep(1.0 + attempt * 2)
        report_lock_failure(
            self.logger,
            "AI调用日志落库",
            last_error,
            detail=describe_exception(last_error),
        )
        with suppress(Exception):
            # 落库失败时至少写入文件日志，保证排障线索不丢
            CallLogger().log_sync(
                    scene=scene,
                    prompt=prompt,
                    response=response,
                    duration_ms=duration_ms,
                    status=status,
                    source_id=source_id,
                    source_name=source_name,
                    model_name=model_name,
                    failover_from=failover_from,
                    project_id=project_id,
                )

    async def call_and_parse(
        self,
        module: str,
        scene: str,
        params: dict[str, Any],
        project_id: str | None = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
        **extra: Any,
    ) -> dict[str, Any]:
        """调用 AI 并解析 JSON 响应.

        Returns:
            解析后的 JSON 字典
        Raises:
            RuntimeError: JSON 解析失败
        """
        result = await self.call(
            module=module,
            scene=scene,
            params=params,
            project_id=project_id,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
        content = result.get("content", "")
        parsed = self._extract_json(content)
        if parsed is None:
            raise RuntimeError(f"AI 返回内容无法解析为 JSON: {content[:200]}")
        result["parsed"] = parsed
        return result

    @staticmethod
    def _escape_in_string_values(text: str) -> str:
        """转义 JSON 字符串值中的字面控制字符（换行/制表/回车）.

        AI 模型常在 JSON 字符串值中返回字面换行符（而非 ``\\n`` 转义），
        这违反 JSON 规范导致 ``json.loads`` 失败。本方法逐字符扫描，
        追踪是否处于字符串值内部，将字面控制字符转义为 JSON 转义序列。
        """
        result: list[str] = []
        in_string = False
        escaped = False
        for ch in text:
            if escaped:
                result.append(ch)
                escaped = False
                continue
            if ch == "\\":
                result.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch == "\n":
                result.append("\\n")
            elif in_string and ch == "\r":
                result.append("\\r")
            elif in_string and ch == "\t":
                result.append("\\t")
            else:
                result.append(ch)
        return "".join(result)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """从文本中提取 JSON（支持 ```json 代码块包裹及截断修复）."""
        if not text:
            return None
        text = text.strip()
        text = text.replace("\uff1a", ":")
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        text = text.replace("\u2018", "'").replace("\u2019", "'")
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        text = AiGateway._escape_in_string_values(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            result = AiGateway._repair_truncated_json(text)
            if result is not None:
                return result
            return AiGateway._extract_fields_by_regex(text)

    @staticmethod
    def _repair_truncated_json(text: str) -> dict[str, Any] | None:
        """尝试修复截断的 JSON：补全缺失的引号、括号、大括号."""
        import re
        match = re.search(r'\{[\s\S]*', text)
        if not match:
            if re.search(r'"\w+"\s*:', text):
                text = "{" + text
                match = re.search(r'\{[\s\S]*', text)
            if not match:
                return None
        fragment = match.group()
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            pass

        # 0) 修复缺失键引号：如 { summary": → {"summary":
        fixed = re.sub(r'\{\s+([a-zA-Z_])', r'{"\1', fragment)
        fixed = re.sub(r',\s+([a-zA-Z_])(\w*)"\s*:', r', "\1\2":', fixed)
        if fixed != fragment:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
            fragment = fixed

        # 1) 键后冒号截断：如 {"name": "X", "identity":（值缺失）
        #    补空字符串值后再补各种闭合组合
        stripped = fragment.rstrip()
        if stripped.endswith(":"):
            base = stripped[:-1] + ': ""'
            for closing in ['}', ']}', '}]}', '}}]}', '}}]}}', '}\n}', '"]}', '"}]}', '"}}]}']:
                try:
                    return json.loads(base + closing)
                except json.JSONDecodeError:
                    continue

        # 1b) 键后冒号+空格截断：如 {"detail": （空格后截断）
        if stripped.endswith(": "):
            base = stripped.rstrip()[:-2] + ': ""'
            for closing in ['}', ']}', '}]}', '}}]}', '}}]}}', '}\n}', '"]}', '"}]}', '"}}]}']:
                try:
                    return json.loads(base + closing)
                except json.JSONDecodeError:
                    continue

        # 2) 常规截断：末尾是半截字符串/数组/对象，尝试补闭合
        for repair in [
            lambda s: s + '"}',
            lambda s: s + '"\n}',
            lambda s: s + '"}]}',
            lambda s: s + '"}]',
            lambda s: s + ']}',
            lambda s: s + '}',
            lambda s: s + '"',
            lambda s: s + '"]}',
            lambda s: s + '"\n}\n',
            lambda s: s + '"}}]}',
            lambda s: s + '"}}]}}',
            lambda s: s + '}}]}',
            lambda s: s + '}}',
        ]:
            try:
                return json.loads(repair(fragment))
            except json.JSONDecodeError:
                continue
        last_quote = fragment.rfind('"')
        if last_quote > 0:
            before_quote = fragment[:last_quote]
            for suffix in ['"}', '"\n}', '"]}', '"}]}']:
                try:
                    return json.loads(before_quote + suffix)
                except json.JSONDecodeError:
                    continue

        # 3) content/content_new 正文中途截断：提取 "content": " 之后的正文（去掉未闭合引号）
        content_slug = re.search(r'"(?:content|content_new)"\s*:\s*"([\s\S]*)', fragment)
        if content_slug:
            raw_content = content_slug.group(1)
            # 去掉末尾可能残留的未闭合引号 / 换行 / 空白
            raw_content = raw_content.rstrip('"\r\n\t ')
            if raw_content.strip():
                # 反转义 JSON 转义序列（\n → 换行等），与 json.loads 行为一致
                try:
                    raw_content = json.loads('"' + raw_content + '"')
                except json.JSONDecodeError:
                    raw_content = raw_content.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
                title_match = re.search(r'"title"\s*:\s*"(.*?)"', fragment, re.DOTALL)
                result = {"title": title_match.group(1) if title_match else "", "content": raw_content}
                if "content_new" in fragment:
                    result["content_new"] = raw_content
                return result

        # 4) 兜底：按 key 提取已闭合的字符串字段
        for key in ["content", "content_new", "synopsis_points_new", "title", "intro", "summary"]:
            val_match = re.search(rf'"{key}"\s*:\s*"(.*?)"', fragment, re.DOTALL)
            if val_match:
                result = {}
                result[key] = val_match.group(1)
                if key in ("content", "content_new"):
                    if key == "content_new":
                        result["content"] = result[key]
                    else:
                        result["content_new"] = result[key]
                title_match = re.search(r'"title"\s*:\s*"(.*?)"', fragment, re.DOTALL)
                if title_match and key != "title":
                    result["title"] = title_match.group(1)
                content_match = re.search(r'"(?:content|content_new)"\s*:\s*"(.*?)"', fragment, re.DOTALL)
                if content_match and key not in ("content", "content_new"):
                    result["content"] = content_match.group(1)
                    result["content_new"] = content_match.group(1)
                if len(result) > 0:
                    return result
        return None

    @staticmethod
    def _extract_fields_by_regex(text: str) -> dict[str, Any] | None:
        """兜底：用正则从混乱/截断的文本中提取 JSON 关键字段.

        当 AI 返回格式严重混乱（中文标点、缺逗号、字段名错误、截断）导致
        json.loads 和 _repair_truncated_json 均失败时，至少提取 score/summary
        等关键字段，避免校验结果整体丢失。
        """
        import re
        result: dict[str, Any] = {}
        score_match = re.search(r'"score"\s*:\s*(\d+)', text)
        if score_match:
            result["score"] = int(score_match.group(1))
        summary_match = re.search(r'"summary"\s*:\s*"(.*?)"', text, re.DOTALL)
        if summary_match:
            result["summary"] = summary_match.group(1)
        content_match = re.search(r'"(?:content|content_new)"\s*:\s*"(.*?)"', text, re.DOTALL)
        if content_match:
            result["content"] = content_match.group(1)
            result["content_new"] = content_match.group(1)
        synopsis_match = re.search(r'"synopsis_points_new"\s*:\s*"(.*?)"', text, re.DOTALL)
        if synopsis_match:
            result["synopsis_points_new"] = synopsis_match.group(1)
        if result:
            return result
        return None


_gateway: AiGateway | None = None


def get_gateway() -> AiGateway:
    global _gateway
    if _gateway is None:
        _gateway = AiGateway()
    return _gateway