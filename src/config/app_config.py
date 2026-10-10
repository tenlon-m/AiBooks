"""应用配置管理 - 基于 pydantic-settings 类型安全配置."""
from __future__ import annotations

import sys
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _frozen() -> bool:
    """是否处于 PyInstaller 打包模式."""
    return bool(getattr(sys, "frozen", False))


def _project_root() -> Path:
    """开发模式下的项目根目录（本文件位于 <root>/src/config/app_config.py）."""
    return Path(__file__).resolve().parents[2]


def _writable_base() -> Path:
    """用户数据可写目录：打包模式下为 exe 所在目录，开发模式下为项目根目录."""
    if _frozen():
        return Path(sys.executable).resolve().parent
    return _project_root()


def _resource_base() -> Path:
    """只读资源目录：打包模式下为解包目录(sys._MEIPASS)，开发模式下为项目根目录."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else _project_root()


class AppConfig(BaseSettings):
    """应用全局配置，支持环境变量与本地配置文件加载."""

    model_config = SettingsConfigDict(
        env_prefix="AIBOOKS_",
        env_file=str(_writable_base() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AiBooks"
    app_version: str = "0.1.0"
    debug: bool = False

    data_dir: Path = Field(default_factory=lambda: _writable_base() / "data")
    backup_dir: Path = Field(default_factory=lambda: _writable_base() / "backups")
    exports_dir: Path = Field(default_factory=lambda: _writable_base() / "exports")
    log_dir: Path = Field(default_factory=lambda: _writable_base() / "data" / "logs")
    prompts_dir: Path = Field(default_factory=lambda: _resource_base() / "src" / "prompts")
    resources_dir: Path = Field(default_factory=lambda: _resource_base() / "src" / "resources")
    templates_dir: Path = Field(default_factory=lambda: _resource_base() / "src" / "templates")

    db_url: str = Field(default="")
    db_echo: bool = False
    db_pool_size: int = 5

    api_host: str = "127.0.0.1"
    api_port: int = 8765

    ai_default_timeout: int = 60
    ai_default_max_retries: int = 3
    ai_health_check_interval: int = 30
    ai_circuit_break_threshold: int = 3
    ai_circuit_break_cool_seconds: int = 60

    writing_words_tolerance: float = 0.2
    writing_chapter_timeout: int = 60
    validation_full_book_timeout: int = 600
    validation_single_chapter_timeout: int = 30
    polish_timeout: int = 60
    rollback_timeout: int = 3

    import_max_file_size_mb: int = 50
    feed_max_total_size_mb: int = 200
    feed_min_single_chars: int = 1000
    batch_revalidate_max_chapters: int = 50

    style_build_timeout: int = 180
    backup_default_retain_count: int = 10

    auto_save_enabled: bool = True
    auto_save_interval_minutes: int = 5
    garbled_detection_enabled: bool = True

    hook_chapter_timeout_seconds: int = 120
    hook_chapter_max_retries: int = 3
    hook_check_consistency_timeout_seconds: int = 180
    writing_check_consistency_timeout_seconds: int = 180
    writing_repair_timeout_seconds: int = 180
    writing_fill_tolerance: float = 0.2
    writing_fill_timeout_seconds: int = 300
    writing_fill_max_retries: int = 2
    chapter_check_consistency_timeout_seconds: int = 30
    style_library_batch_delete_timeout_seconds: int = 2
    writing_save_timeout_seconds: int = 3
    writing_chapter_timeout_seconds: int = 180
    writing_chapter_max_retries: int = 3
    outline_generate_timeout_seconds: int = 300
    outline_batch_chapters: int = 10
    outline_batch_timeout_seconds: int = 90
    outline_batch_prev_context: int = 20
    outline_fill_appearing_timeout_seconds: int = 90
    outline_repair_timeout_seconds: int = 120
    validation_character_count_timeout_seconds: int = 120
    creation_polish_synopsis_timeout_seconds: int = 90
    creation_polish_worldview_timeout_seconds: int = 90

    log_level: str = "INFO"
    log_rotation: str = "10 MB"
    log_retention: str = "30 days"

    writing_chat_timeout_seconds: int = 120
    text_transform_timeout_seconds: int = 60
    connection_analyze_timeout_seconds: int = 120
    scene_split_timeout_seconds: int = 90
    naming_generate_timeout_seconds: int = 180
    chapter_summary_timeout_seconds: int = 60
    emotion_analyze_timeout_seconds: int = 90
    character_extract_timeout_seconds: int = 120
    hook_design_timeout_seconds: int = 120
    hook_repair_timeout_seconds: int = 120
    chapter_version_max_keep: int = 20
    batch_replace_max_matches: int = 1000
    sensitive_word_scan_batch_size: int = 50
    export_timeout_seconds: int = 30
    min_ai_content_length: int = 50
    reading_mode_default_font_size: int = 18
    reading_mode_default_line_spacing: float = 1.8
    shortcut_conflict_check_enabled: bool = True

    anti_ai_rewrite_timeout_seconds: int = 60
    batch_extract_timeout_seconds: int = 90
    batch_rewrite_timeout_seconds: int = 60
    book_teardown_timeout_seconds: int = 120
    item_extract_timeout_seconds: int = 120
    iteration_timeout_seconds: int = 90
    script_generate_timeout_seconds: int = 90
    proofread_timeout_seconds: int = 90
    evaluate_timeout_seconds: int = 60
    story_unit_generate_timeout_seconds: int = 60

    # SQLite 长写事务看门狗：任何写事务持有超过阈值秒数就打 WARNING 并指出
    # 开事务的代码位置。正常业务写入都是毫秒级，所以超过阈值基本就是"攥着写锁
    # 去调 AI"的 bug —— 不必等别人撞锁报错就能提前发现。
    lock_watchdog_enabled: bool = True
    lock_watchdog_interval_seconds: float = 5.0
    lock_watchdog_threshold_seconds: float = 20.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "aibooks.db"

    @model_validator(mode="after")
    def _sync_db_url(self) -> AppConfig:
        if not self.db_url:
            self.db_url = f"sqlite+aiosqlite:///{self.db_path.as_posix()}"
        return self

    def ensure_dirs(self) -> None:
        # 只初始化可写目录；prompts/templates/resources 属只读资源（打包后位于
        # sys._MEIPASS 解包目录），不在此创建，避免安装到只读位置时触发
        # PermissionError 阻断启动。
        for d in (self.data_dir, self.backup_dir, self.log_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)