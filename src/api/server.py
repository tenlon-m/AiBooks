"""FastAPI 内嵌服务器 - Uvicorn 在 QThread 中启动 ASGI 事件循环."""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from src.utils.logger import get_logger

_app: FastAPI | None = None
_server_thread: threading.Thread | None = None
_server = None
_server_started = threading.Event()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """应用生命周期：启停长写事务看门狗.

    看门狗是"提前发现"手段：只要有任何写事务持有 SQLite 写锁超过阈值秒数，
    就立刻在日志里打出开事务的代码位置。这样即便还没有人撞到
    ``database is locked``，也能第一时间发现"攥着写锁去调 AI"的 bug。
    """
    watchdog: asyncio.Task | None = None
    try:
        from src.config.settings import get_config

        cfg = get_config()
        if cfg.lock_watchdog_enabled:
            from src.db.lock_diagnostics import long_transaction_watchdog

            watchdog = asyncio.create_task(
                long_transaction_watchdog(
                    interval_seconds=cfg.lock_watchdog_interval_seconds,
                    threshold_seconds=cfg.lock_watchdog_threshold_seconds,
                ),
                name="lock-watchdog",
            )
    except Exception as e:  # noqa: BLE001 - 诊断功能不可用时不应影响服务启动
        get_logger().warning(f"长写事务看门狗启动失败（已忽略）: {e}")

    try:
        yield
    finally:
        if watchdog is not None:
            watchdog.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await watchdog


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册所有路由."""
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title="AiBooks API",
        version="0.1.0",
        description="AI 全自动小说撰写软件后端 API",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routers(app)
    return app


# 路由注册清单：(模块名, 前缀, tag)。顺序即注册顺序，影响路径匹配优先级：
# 带路径参数的路由（如 item_router 的 /{project_id}）必须排在具体子路径之后。
_ROUTER_SPECS: list[tuple[str, str, str]] = [
    ("creation_router", "/api/creation", "创作参数"),
    ("import_router", "/api/import", "文件导入"),
    ("character_router", "/api/characters", "人物管理"),
    ("hook_router", "/api/hooks", "爽点钩子"),
    ("style_library_router", "/api/style-libraries", "风格库"),
    ("writing_router", "/api/writing", "批量撰写"),
    ("validation_router", "/api/validation", "内容校验"),
    ("chapter_router", "/api/chapters", "章节修改"),
    ("export_router", "/api/export", "小说导出"),
    ("ai_source_router", "/api/config", "AI源配置"),
    ("project_router", "/api/projects", "项目迁移"),
    ("backup_router", "/api/backup", "备份管理"),
    ("ai_call_log_router", "/api/ai_logs", "AI调用日志"),
    ("outline_router", "/api/outlines", "大纲管理"),
    ("writing_chat_router", "/api/writing-chat", "AI对话写作"),
    ("text_transform_router", "/api/text-transform", "文本变换"),
    ("connection_router", "/api/connection", "章节衔接"),
    ("scene_outline_router", "/api/scene-outline", "场景大纲"),
    ("naming_router", "/api/naming", "命名生成"),
    ("template_library_router", "/api/template-library", "写作模板库"),
    ("layout_template_router", "/api/layout-templates", "排版模板"),
    ("timeline_router", "/api/timeline", "时间线管理"),
    ("relationship_router", "/api/relationships", "角色关系图谱"),
    ("emotion_router", "/api/emotion", "情感曲线分析"),
    ("word_stats_router", "/api/stats", "字数统计"),
    ("sensitive_word_router", "/api/sensitive", "敏感词检测"),
    ("chapter_summary_router", "/api/summaries", "章节摘要"),
    ("shortcut_router", "/api/shortcuts", "快捷键配置"),
    ("batch_replace_router", "/api/chapters/replace", "批量查找替换"),
    ("chapter_merge_router", "/api/chapters", "章节合并拆分"),
    ("outline_reorder_router", "/api/outline", "大纲拖拽排序"),
    ("chapter_version_router", "/api/chapters", "章节版本管理"),
    ("annotation_router", "/api/chapters/annotations", "章节批注"),
    ("item_router", "/api/items", "物品管理"),
    ("anti_ai_router", "/api/anti-ai", "降AI率改写"),
    ("batch_edit_router", "/api/batch-edit", "批量提取/改写"),
    ("book_teardown_router", "/api/book-teardown", "一键拆书"),
    ("iteration_router", "/api/iteration", "迭代生成"),
    ("script_router", "/api/script", "AI写剧本"),
    ("proofread_router", "/api/proofread", "多AI纠错"),
    ("story_unit_router", "/api/story-units", "故事单元"),
]


def _register_routers(app: FastAPI) -> None:
    """注册所有业务路由（延迟导入避免循环依赖）.

    注册失败会在日志里报 ERROR 而不是静默跳过——此前 34 处
    ``except ImportError: pass`` 让「路由模块导入失败」完全不可见，
    表现为前端点按钮 404 却查不到任何线索。
    """
    import importlib

    logger = get_logger()
    failed: list[tuple[str, str, str]] = []
    for module_name, prefix, tag in _ROUTER_SPECS:
        try:
            module = importlib.import_module(f"src.api.routers.{module_name}")
        except Exception as e:  # noqa: BLE001 - 单个路由模块不可用不应拖垮整个服务
            logger.error(f"路由注册失败，{prefix} 下接口将全部 404：{module_name}: {e!r}")
            failed.append((module_name, prefix, tag))
            continue
        try:
            app.include_router(module.router, prefix=prefix, tags=[tag])
        except Exception as e:  # noqa: BLE001
            logger.error(f"路由挂载失败（prefix={prefix}）：{module_name}: {e!r}")
            failed.append((module_name, prefix, tag))

    if failed:
        # 打包运行时（console=False）看不到控制台，这条汇总会落进 data/logs，
        # 是定位「打包后接口 404」的第一现场。
        logger.error(
            f"路由注册完成，但有 {len(failed)}/{len(_ROUTER_SPECS)} 个模块未注册，"
            f"相关接口将 404：{[f'{tag}({prefix})' for _, prefix, tag in failed]}"
        )
    else:
        logger.info(f"路由注册完成：{len(_ROUTER_SPECS)} 个模块全部注册成功")


def get_app() -> FastAPI:
    global _app
    if _app is None:
        _app = create_app()
    return _app


def start_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    """在独立线程中启动 Uvicorn 服务器（非阻塞）."""
    global _server_thread, _server
    import uvicorn

    logger = get_logger()
    app = get_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    _server = uvicorn.Server(config)

    def _run() -> None:
        try:
            _server.run()
        except Exception as e:
            logger.error(f"FastAPI 服务器异常: {e}")
        finally:
            _server_started.clear()

    _server_thread = threading.Thread(target=_run, daemon=True, name="aibooks-api")
    _server_thread.start()

    import httpx
    for _ in range(50):
        try:
            r = httpx.get(f"http://{host}:{port}/docs", timeout=0.5)
            if r.status_code == 200:
                break
        except Exception:
            pass
        import time
        time.sleep(0.1)
    logger.info(f"FastAPI 服务器已启动: http://{host}:{port}")


def stop_server() -> None:
    """停止服务器."""
    global _server_thread, _server
    if _server is not None:
        try:
            _server.should_exit = True
        except Exception:
            pass
        _server = None
    if _server_thread is not None and _server_thread.is_alive():
        elapsed = 0.0
        while _server_thread.is_alive() and elapsed < 5.0:
            _server_thread.join(timeout=0.1)
            if _server_thread.is_alive():
                elapsed += 0.1
                try:
                    from PySide6.QtWidgets import QApplication

                    QApplication.processEvents()
                except Exception:
                    pass
    _server_thread = None