"""路由策略快照 - 脱离 ORM 会话的纯数据副本.

背景：AiGateway 是单例，把 RoutingPolicy ORM 实例传给 ModelRouter/HealthChecker
长期缓存；该实例绑定在首次调用的会话上，会话 commit/close 后属性过期、实例游离，
下一次调用再读 policy.strategy 就抛
"Instance <RoutingPolicy ...> is not bound to a Session"
（DetachedInstanceError, https://sqlalche.me/e/20/bhk3），
在界面表现为"AI分批生成大纲失败：API 502 ..."——第一批成功、第二批必挂。

方案：在会话存活期内把列值拍成纯 dataclass 快照，路由组件只依赖快照；
快照与缓存不一致（用户修改了路由策略）时由网关重建路由器。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RoutingPolicySnapshot:
    """routing_policies 表单行的纯数据镜像（可安全跨会话持有）."""

    strategy: str = "failover"
    manual_source_id: str | None = None
    health_check_interval_seconds: int = 30
    circuit_break_threshold: int = 3
    circuit_break_cool_seconds: int = 60
    failover_within_retry: bool = True
    updated_at: datetime | None = None

    @classmethod
    def from_model(cls, policy: Any) -> RoutingPolicySnapshot:
        """从 ORM 实例拍快照（必须在实例所属会话关闭前调用）."""
        return cls(
            strategy=str(policy.strategy or "failover"),
            manual_source_id=policy.manual_source_id,
            health_check_interval_seconds=int(
                policy.health_check_interval_seconds or 30
            ),
            circuit_break_threshold=int(policy.circuit_break_threshold or 3),
            circuit_break_cool_seconds=int(policy.circuit_break_cool_seconds or 60),
            failover_within_retry=bool(policy.failover_within_retry),
            updated_at=policy.updated_at,
        )
