"""乱码检测修复配置 ORM 模型 - 从 base 重导出以支持独立导入."""
from __future__ import annotations

from src.db.models.base import GarbledConfigModel

__all__ = ["GarbledConfigModel"]