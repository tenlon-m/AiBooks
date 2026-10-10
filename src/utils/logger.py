"""日志系统 - 基于 loguru 分级日志，文件轮转与控制台双写."""
from __future__ import annotations

import sys

from loguru import logger

from src.config.app_config import AppConfig

_initialized = False


def init_logger(config: AppConfig) -> None:
    global _initialized
    if _initialized:
        return
    config.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()

    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=config.log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        )

    logger.add(
        config.log_dir / "app_{time:YYYY-MM-DD}.log",
        level=config.log_level,
        rotation=config.log_rotation,
        retention=config.log_retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} - {message}",
    )

    logger.add(
        config.log_dir / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        rotation=config.log_rotation,
        retention=config.log_retention,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} - {message}",
    )

    _initialized = True


def get_logger():
    return logger