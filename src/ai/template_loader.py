"""提示词模板加载器 - 支持热重载与版本管理."""
from __future__ import annotations

import threading
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from src.config.app_config import AppConfig
from src.utils.logger import get_logger


class TemplateLoader:
    """加载 manifest.yaml 建立索引，按 module+scene 查找模板.

    支持 source_type 覆盖变体路径与热重载。
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.prompts_dir = config.prompts_dir
        self.logger = get_logger()
        self._manifest: dict[str, dict[str, Any]] = {}
        self._variables: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._env = Environment(
            loader=FileSystemLoader(str(self.prompts_dir)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True,
            enable_async=False,
        )
        self._watcher_started = False

    def load(self) -> None:
        """加载 manifest.yaml 与 variables.yaml 建立索引."""
        with self._lock:
            manifest_path = self.prompts_dir / "manifest.yaml"
            variables_path = self.prompts_dir / "variables.yaml"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._manifest = {}
                for t in data.get("templates", []):
                    key = f"{t['module']}.{t['scene']}"
                    self._manifest[key] = t
            if variables_path.exists():
                with open(variables_path, "r", encoding="utf-8") as f:
                    self._variables = yaml.safe_load(f) or {}
            self.logger.info(f"模板索引加载完成，共 {len(self._manifest)} 个模板")

    def get_template_info(self, module: str, scene: str) -> dict[str, Any] | None:
        key = f"{module}.{scene}"
        return self._manifest.get(key)

    def resolve_file(self, module: str, scene: str, source_type: str | None = None) -> str:
        """解析模板文件路径，支持 source_type 覆盖."""
        info = self.get_template_info(module, scene)
        if info is None:
            raise TemplateNotFound(f"{module}.{scene}")
        if source_type and "source_type_overrides" in info:
            override = info["source_type_overrides"].get(source_type)
            if override:
                return override
        return info["file"]

    def render(self, module: str, scene: str, params: dict[str, Any], source_type: str | None = None) -> str:
        """渲染模板返回提示词字符串."""
        with self._lock:
            file_path = self.resolve_file(module, scene, source_type)
            template = self._env.get_template(file_path)
            global_vars = self._variables.get("global", {})
            render_params = {**global_vars, **params}
            if source_type:
                overrides = self._variables.get("source_type_overrides", {}).get(source_type, {})
                render_params.update(overrides)
            return template.render(**render_params)

    def validate_params(self, module: str, scene: str, params: dict[str, Any]) -> None:
        """静态检查参数是否满足 variables.yaml 声明."""
        key = f"{module}.{scene}"
        scenes = self._variables.get("scenes", {})
        scene_def = scenes.get(key, {})
        for var_name, var_def in scene_def.items():
            if var_def.get("required", False) and var_name not in params:
                raise PromptRenderError(f"模板 {key} 缺少必填变量: {var_name}")

    def start_watch(self) -> None:
        """启动 watchfiles 监听模板目录变更."""
        if self._watcher_started:
            return
        try:
            import asyncio
            from watchfiles import awatch

            async def _watch() -> None:
                async for _ in awatch(str(self.prompts_dir)):
                    self.logger.info("检测到模板文件变更，重新加载...")
                    self.load()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_watch())
                else:
                    asyncio.run(_watch())
            except RuntimeError:
                pass
            self._watcher_started = True
        except ImportError:
            self.logger.warning("watchfiles 未安装，模板热重载不可用")

    def reload(self) -> None:
        """手动重新加载."""
        self.load()


class PromptRenderError(Exception):
    """提示词渲染错误."""

    pass


_loader: TemplateLoader | None = None


def get_template_loader(config: AppConfig | None = None) -> TemplateLoader:
    global _loader
    if _loader is None:
        if config is None:
            from src.config.settings import get_config
            config = get_config()
        _loader = TemplateLoader(config)
        _loader.load()
    return _loader