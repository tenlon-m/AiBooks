"""提示词渲染器 - PromptBuilder Jinja2 渲染入口."""
from __future__ import annotations

from typing import Any

from src.ai.template_loader import PromptRenderError, get_template_loader


class PromptBuilder:
    """接收 (module, scene, params, source_type) 渲染提示词.

    按 variables.yaml 场景定义校验入参，渲染模板返回最终提示词字符串。
    """

    def __init__(self, loader=None) -> None:
        self.loader = loader or get_template_loader()

    def build(
        self,
        module: str,
        scene: str,
        params: dict[str, Any],
        source_type: str | None = None,
    ) -> str:
        """渲染提示词.

        Args:
            module: 模块名（character/hook/writing/validation/polish/style）
            scene: 场景名（extract-main/write-chapter 等）
            params: 模板参数
            source_type: AI 源类型，用于选择模板变体

        Returns:
            渲染后的提示词字符串

        Raises:
            PromptRenderError: 参数校验失败或模板不存在
        """
        self.loader.validate_params(module, scene, params)
        return self.loader.render(module, scene, params, source_type)


_builder: PromptBuilder | None = None


def get_prompt_builder() -> PromptBuilder:
    global _builder
    if _builder is None:
        _builder = PromptBuilder()
    return _builder