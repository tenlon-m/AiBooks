"""创作日志 - 单独归档记录批量撰写每步执行情况."""
from __future__ import annotations


from loguru import logger

from src.config.app_config import AppConfig

_initialized = False


def init_creation_logger(config: AppConfig) -> None:
    global _initialized
    if _initialized:
        return
    config.log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        config.log_dir / "creation_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation=config.log_rotation,
        retention=config.log_retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
        filter=lambda record: "creation" in record["extra"],
    )
    _initialized = True


def log_writing_step(
    project_id: str,
    volume_no: int,
    chapter_no: int,
    status: str,
    duration_ms: int = 0,
    extra: str = "",
) -> None:
    msg = f"[creation] project={project_id} vol={volume_no} ch={chapter_no} status={status} duration={duration_ms}ms"
    if extra:
        msg += f" | {extra}"
    logger.bind(creation=True).info(msg)