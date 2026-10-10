"""应用入口 - 初始化配置/日志/数据库/服务器并启动UI."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

# 直接运行 python src/app.py 时，sys.path[0] 是 src/ 而非项目根目录，
# 需要把项目根目录加入搜索路径，否则 from src.xxx 全部失败。
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 兼容性补丁必须在导入 PySide6 / matplotlib 之前执行，
# 否则 six.moves 伪模块会让 shiboken 的 import hook 抛 AttributeError（详见模块内说明）。
from src.utils.compat import apply_six_namespace_fix

apply_six_namespace_fix()


class PresetModel(TypedDict):
    """ai_source_config_page.PRESET_MODELS 中单个预置模型条目的类型结构.

    该常量未显式标注类型，字段值同时包含 str/list[str]/bool，取值会被推断为
    str | list[str] | bool 联合类型而无法匹配 AiSourceCreateRequest 的字段类型。
    用此结构对其做一次 cast，可恢复各字段的精确类型（静态检查用，运行期无副作用）。
    """

    name: str
    source_type: Literal["online_openai_compatible", "local_ollama"]
    api_endpoint: str
    model_name: str
    tags: list[str]
    task_tags: list[str]
    priority: int
    needs_api_key: bool
    register_url: str
    desc: str
    is_ollama_template: NotRequired[bool]


def init_app() -> None:
    """初始化应用基础设施."""
    from src.config.app_config import AppConfig
    from src.config.crypto import init_crypto
    from src.config.settings import get_config
    from src.utils.logger import init_logger
    from src.utils.creation_logger import init_creation_logger
    from src.db.session import init_engine

    config = get_config()
    config.ensure_dirs()
    init_logger(config)
    init_creation_logger(config)
    init_crypto(config)
    init_engine(config)

    from src.db.migrations.init_schema import init_schema
    from src.db.migrations.add_character_supporting_fields import upgrade as upgrade_chars
    from src.db.migrations.add_outline_tables import upgrade as upgrade_outlines
    from src.db.migrations.add_chapter_appearing_characters import (
        upgrade as upgrade_appearing,
    )
    from src.db.migrations.add_feature_gap_fill_tables import (
        upgrade as upgrade_gap_fill,
    )
    from src.db.migrations.add_name_favorite_meaning import (
        upgrade as upgrade_naming_meaning,
    )
    from src.db.migrations.add_garbled_configs import (
        upgrade as upgrade_garbled_configs,
    )
    from src.db.migrations.add_tangku_new_tables import (
        upgrade as upgrade_tangku_tables,
    )
    from src.db.migrations.add_tangku_new_columns import (
        upgrade as upgrade_tangku_columns,
    )
    from src.utils.async_bridge import get_bridge

    bridge = get_bridge()
    bridge.run_async(init_schema())
    bridge.run_async(upgrade_chars())
    bridge.run_async(upgrade_outlines())
    bridge.run_async(upgrade_appearing())
    # 12 张功能表 + chapters.is_locked：老库缺列会导致所有章节查询报
    # "no such column: chapters.is_locked"（迁移幂等，可安全重复执行）
    bridge.run_async(upgrade_gap_fill())
    bridge.run_async(upgrade_naming_meaning())
    bridge.run_async(upgrade_garbled_configs())
    bridge.run_async(upgrade_tangku_tables())
    bridge.run_async(upgrade_tangku_columns())

    from src.db.session import session_scope
    from src.services.style_library_service import StyleLibraryService

    async def _init_default_style():
        async with session_scope() as session:
            service = StyleLibraryService(session)
            await service.ensure_default_style()

    bridge.run_async(_init_default_style())

    from src.services.ai_source_service import AiSourceService
    from src.api.schemas.ai_source_schema import AiSourceCreateRequest

    async def _init_preset_ai_sources():
        async with session_scope() as session:
            service = AiSourceService(session)
            existing = await service.list_all()
            if existing:
                return
            from src.ui.pages.ai_source_config_page import PRESET_MODELS
            for preset in cast(list[PresetModel], PRESET_MODELS):
                try:
                    req = AiSourceCreateRequest(
                        name=preset["name"],
                        source_type=preset["source_type"],
                        api_endpoint=preset["api_endpoint"],
                        model_name=preset["model_name"],
                        api_key=None,
                        timeout_seconds=60,
                        max_retries=3,
                        priority=int(preset.get("priority", 1)),
                        weight=1,
                        enabled=False,
                        tags=preset["tags"],
                        task_tags=list(preset.get("task_tags") or []),
                    )
                    await service.create(req)
                except Exception as e:
                    from src.utils.logger import get_logger

                    get_logger().warning(f"预置 AI 源插入失败: {preset.get('name', '?')} - {e}")

    bridge.run_async(_init_preset_ai_sources())


def main() -> None:
    """主入口."""
    import io
    import os

    # PyInstaller 打包后 console=False 时 sys.stdout/sys.stderr 均为 None，
    # uvicorn 等库构造日志 handler 时会调用 .isatty() 崩溃，此处补齐为 devnull 兜底。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    init_app()

    from src.utils.logger import get_logger

    get_logger().info("******程序开始运行******")

    from PySide6.QtWidgets import QApplication
    from src.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    # 全局接管消息弹窗：失败详情可划选/一键复制（MainWindow 内幂等再装一次）
    from src.ui.widgets.copyable_message import install_copyable_message_boxes

    install_copyable_message_boxes()

    from src.ui.icon_manager import IconManager

    IconManager.load_and_set_icon(app)

    from src.api.server import start_server
    from src.config.settings import get_config
    config = get_config()
    start_server(config.api_host, config.api_port)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()