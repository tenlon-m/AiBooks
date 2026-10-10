"""模型特点识别 - 根据模型名推断中文特点并推荐适用任务.

设计目标：
- 用户新增任意在线模型后，点击"测试连接"即可看到该模型的中文特点说明
  （模型族、参数量级、速度/质量评级、擅长方向），并得到"推荐勾选哪些适用任务"的建议。
- 识别策略：先查已知模型表（精确），再回退到基于模型名关键词 + 参数量级的通用启发式（泛化），
  保证任何未知模型也能给出有参考价值的说明。

本模块为纯函数实现，不依赖网络与数据库，便于单元测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 任务标签（与 gateway.call(module=...) 的 module 名一一对应）
TASK_LABELS: dict[str, str] = {
    "outline": "大纲生成/校验",
    "writing": "章节正文",
    "character": "人物管理",
    "hook": "爽点/钩子",
    "validation": "内容校验",
    "polish": "润色",
    "style": "风格库",
}

# 写作类任务集合（非大纲的其余任务，对速度与吞吐更敏感）
WRITING_TASKS: list[str] = [
    "writing",
    "character",
    "hook",
    "validation",
    "polish",
    "style",
]

# 模型族识别：厂商关键词 → 中文族名（按顺序匹配，命中即止）
# 用正则而非裸子串：避免 "moonshot" 误命中 "o1" 之类的短 token 冲突。
_FAMILY_RULES: list[tuple[str, str]] = [
    (r"qwen|qwq|tongyi|通义", "通义千问"),
    (r"deepseek", "DeepSeek"),
    (r"glm|chatglm|智谱", "智谱GLM"),
    (r"moonshot|kimi", "月之暗面Kimi"),
    (r"ernie|文心", "百度文心"),
    (r"hunyuan|混元", "腾讯混元"),
    (r"doubao|豆包|seed-", "字节豆包"),
    (r"minimax|abab", "MiniMax"),
    (r"step-|阶跃", "阶跃星辰"),
    (r"spark|星火", "讯飞星火"),
    (r"零一万物|(?<![a-z])yi-", "零一万物Yi"),
    (r"baichuan|百川", "百川智能"),
    (r"claude", "Anthropic Claude"),
    (r"gemini", "Google Gemini"),
    (r"gpt|(?<![a-z])o[134](?![a-z0-9])", "OpenAI"),
    (r"llama", "Meta Llama"),
    (r"mistral|mixtral|magistral", "Mistral"),
    (r"gemma", "Google Gemma"),
    (r"(?<![a-z])phi(?![a-z0-9])", "微软 Phi"),
]

# 关键词分两级匹配，兼顾"防误命中"与"允许词形变化"：
# - strict：前后都要求词边界。用于极易被子串误命中的短 token，
#   例 'mini' 不能命中 'minimax'、'4b' 不能命中 '14b'、'max' 不能命中 'minimax'。
# - loose：允许前缀/词形变化。例 'reason' 需命中 'reasoner'、'think' 需命中 'thinking'。
_STRICT_REASONING = ("r1", "o1", "o3", "o4", "qwq")
_LOOSE_REASONING = ("reason", "think", "long-cot")

_STRICT_LIGHTWEIGHT = ("mini", "lite", "air", "8b", "7b", "4b", "3b", "1.5b", "0.5b")
_LOOSE_LIGHTWEIGHT = ("flash", "turbo", "small", "nano", "tiny", "fast", "instant")

_STRICT_FLAGSHIP = ("max", "plus", "pro", "opus", "72b", "70b", "110b", "235b", "405b", "671b")
_LOOSE_FLAGSHIP = ("ultra", "large")


def _keyword_matcher(
    strict: tuple[str, ...], loose: tuple[str, ...]
) -> re.Pattern[str]:
    """编译"严格边界 + 宽松子串"组合正则.

    严格项：关键词前后紧邻字母/数字时不算命中（``-`` / ``:`` / ``/`` 等视为边界）。
    宽松项：直接子串匹配，允许 ``reason`` 命中 ``reasoner`` 这类词形变化。
    """
    parts = [r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])" for k in strict]
    parts += [re.escape(k) for k in loose]
    return re.compile("|".join(parts), re.IGNORECASE)


_REASONING_RE = _keyword_matcher(_STRICT_REASONING, _LOOSE_REASONING)
_LIGHTWEIGHT_RE = _keyword_matcher(_STRICT_LIGHTWEIGHT, _LOOSE_LIGHTWEIGHT)
_FLAGSHIP_RE = _keyword_matcher(_STRICT_FLAGSHIP, _LOOSE_FLAGSHIP)


# 已知模型精确档案（key 为小写子串，按长度倒序匹配，长 key 优先）
_KNOWN_MODELS: dict[str, dict[str, Any]] = {
    "qwen2.5-72b": {
        "scale": "72B", "speed": "慢", "quality": "极高",
        "tasks": ["outline"],
        "strengths": ["中文叙事与构思最佳", "结构化 JSON 极稳", "长上下文一致性最强"],
    },
    "qwen2.5-32b": {
        "scale": "32B", "speed": "中等偏慢", "quality": "高",
        "tasks": ["outline"],
        "strengths": ["中文情节张力与伏笔更细腻", "结构化 JSON 输出稳定", "前情衔接把握准"],
    },
    "qwen2.5-14b": {
        "scale": "14B", "speed": "中等", "quality": "中上",
        "tasks": WRITING_TASKS,
        "strengths": ["中文写作质量明显优于 7B", "速度与质量平衡好", "批量正文性价比高"],
    },
    "qwen2.5-7b": {
        "scale": "7B", "speed": "快", "quality": "中等",
        "tasks": [],
        "strengths": ["响应快、免费额度充足", "适合大批量轻量任务", "作为通用兜底稳定"],
    },
    "qwen-turbo": {
        "scale": "未知(轻量)", "speed": "快", "quality": "中等",
        "tasks": [],
        "strengths": ["响应快、成本极低", "适合校验/润色等辅助任务", "作为通用兜底"],
    },
    "qwen-plus": {
        "scale": "未知(中大型)", "speed": "中等", "quality": "中上",
        "tasks": WRITING_TASKS,
        "strengths": ["中文能力均衡", "长上下文支持好", "性价比高"],
    },
    "qwen-max": {
        "scale": "未知(旗舰)", "speed": "中等偏慢", "quality": "高",
        "tasks": ["outline"],
        "strengths": ["阿里最强中文模型", "复杂指令遵循好", "适合关键大纲"],
    },
    "deepseek-reasoner": {
        "scale": "未知(推理型)", "speed": "慢", "quality": "极高(推理)",
        "tasks": ["outline"],
        "strengths": ["深度推理与逻辑推演强", "适合复杂世界观架构", "输出较慢、成本偏高"],
    },
    "deepseek-v3": {
        "scale": "未知(旗舰)", "speed": "中等", "quality": "高",
        "tasks": ["outline", "writing"],
        "strengths": ["中文写作质量极佳", "长文本连贯性好", "价格极低性价比突出"],
    },
    "deepseek-chat": {
        "scale": "未知(旗舰)", "speed": "中等", "quality": "高",
        "tasks": ["outline", "writing"],
        "strengths": ["中文写作质量极佳", "长文本连贯性好", "价格极低性价比突出"],
    },
    "glm-4-flash": {
        "scale": "未知(轻量)", "speed": "快", "quality": "中等",
        "tasks": [],
        "strengths": ["完全免费", "响应快", "适合校验/兜底"],
    },
    "glm-4-plus": {
        "scale": "未知(旗舰)", "speed": "中等", "quality": "高",
        "tasks": ["outline", "writing"],
        "strengths": ["中文理解与创作好", "长上下文支持好", "指令遵循稳定"],
    },
    "glm-4": {
        "scale": "未知(中大型)", "speed": "中等", "quality": "中上",
        "tasks": ["writing"],
        "strengths": ["中文能力强", "适合正文与人物", "生态成熟"],
    },
    "moonshot-v1-128k": {
        "scale": "未知(长上下文)", "speed": "中等", "quality": "中上",
        "tasks": ["outline"],
        "strengths": ["128K 超长上下文", "擅长通读全书设定", "适合大纲与前情衔接"],
    },
    "moonshot-v1-32k": {
        "scale": "未知(长上下文)", "speed": "中等", "quality": "中上",
        "tasks": ["writing"],
        "strengths": ["32K 长上下文", "中文写作流畅", "适合长章节正文"],
    },
    "moonshot-v1-8k": {
        "scale": "未知(短上下文)", "speed": "快", "quality": "中等",
        "tasks": [],
        "strengths": ["响应快、成本低", "适合短文本任务", "作为通用兜底"],
    },
}

_SIZE_RE = re.compile(r"(?<![a-z0-9])(\d{1,4}(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)


@dataclass
class ModelProfile:
    """模型特点档案（供"测试连接"结果展示与任务推荐）."""

    model_name: str
    family: str
    scale: str
    speed: str
    quality: str
    is_reasoning: bool
    is_lightweight: bool
    is_flagship: bool = False
    strengths: list[str] = field(default_factory=list)
    recommended_tasks: list[str] = field(default_factory=list)
    recommend_as_fallback: bool = False
    summary: str = ""
    advice: str = ""
    matched_by: str = "heuristic"  # known | heuristic

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "family": self.family,
            "scale": self.scale,
            "speed": self.speed,
            "quality": self.quality,
            "is_reasoning": self.is_reasoning,
            "is_lightweight": self.is_lightweight,
            "is_flagship": self.is_flagship,
            "strengths": list(self.strengths),
            "recommended_tasks": list(self.recommended_tasks),
            "recommend_as_fallback": self.recommend_as_fallback,
            "summary": self.summary,
            "advice": self.advice,
            "positioning": self.positioning,
            "matched_by": self.matched_by,
        }

    @property
    def recommended_task_labels(self) -> list[str]:
        return [TASK_LABELS.get(t, t) for t in self.recommended_tasks]

    @property
    def positioning(self) -> str:
        """模型定位（中文一句话），用于界面展示."""
        if self.is_reasoning:
            return "推理型模型：慢而强，适合复杂构思与结构化推理"
        if self.is_lightweight:
            return "轻量快模型：响应快、成本低，适合大批量辅助任务或兜底"
        if self.is_flagship:
            return "大型旗舰模型：质量优先、速度偏慢，适合关键大纲"
        return "均衡型模型：速度与质量兼顾，适合作为主力写作模型"


def _detect_family(name_lower: str) -> str:
    for pattern, family in _FAMILY_RULES:
        if re.search(pattern, name_lower):
            return family
    return "未知/自定义"


def _extract_size(name_lower: str) -> float | None:
    """从模型名中提取参数量级(B)，返回数值；提取不到返回 None."""
    matches = _SIZE_RE.findall(name_lower)
    if not matches:
        return None
    try:
        return max(float(m) for m in matches)
    except ValueError:
        return None


def _match_known(name_lower: str) -> tuple[str, dict[str, Any]] | None:
    """按 key 长度倒序匹配已知模型（保证更具体的 key 优先命中）."""
    for key in sorted(_KNOWN_MODELS, key=len, reverse=True):
        if key in name_lower:
            return key, _KNOWN_MODELS[key]
    return None


def _latency_text(latency_ms: int | None) -> str:
    if latency_ms is None:
        return ""
    if latency_ms < 1200:
        return "实测响应极快"
    if latency_ms < 2500:
        return "实测响应较快"
    if latency_ms < 5000:
        return "实测响应中等"
    return "实测响应偏慢"


def build_model_profile(model_name: str, latency_ms: int | None = None) -> ModelProfile:
    """根据模型名（可选实测延迟）构建中文特点档案与任务推荐.

    Args:
        model_name: 模型名称，如 ``Qwen/Qwen2.5-32B-Instruct`` / ``glm-4-flash``
        latency_ms: 测试连接实测耗时（毫秒）；为空时不叠加实测速度描述

    Returns:
        ModelProfile
    """
    raw_name = (model_name or "").strip()
    name_lower = raw_name.lower()
    family = _detect_family(name_lower)
    size = _extract_size(name_lower)
    is_reasoning = bool(_REASONING_RE.search(name_lower))
    is_lightweight = bool(_LIGHTWEIGHT_RE.search(name_lower)) or (
        size is not None and size < 12
    )
    is_flagship = bool(_FLAGSHIP_RE.search(name_lower)) or (
        size is not None and size >= 30
    )

    known = _match_known(name_lower)
    lat = _latency_text(latency_ms)

    if known is not None:
        _, info = known
        scale = info.get("scale") or (f"{size:g}B" if size else "未知")
        speed = info["speed"]
        quality = info["quality"]
        tasks = list(info["tasks"])
        strengths = list(info["strengths"])
        matched_by = "known"
        model_label = f"{family} {raw_name}" if family != "未知/自定义" else raw_name
    else:
        scale = f"{size:g}B" if size else "未知"
        matched_by = "heuristic"
        model_label = f"{family} {raw_name}" if family != "未知/自定义" else raw_name
        if is_reasoning:
            speed, quality = "慢", "很高(推理强)"
            tasks = ["outline"]
            strengths = [
                "深度推理与逻辑推演强",
                "适合复杂世界观与伏笔架构",
                "输出较慢，建议仅用于关键大纲",
            ]
        elif is_flagship:
            speed, quality = "中等偏慢", "高"
            tasks = ["outline"]
            strengths = [
                "参数量大、中文叙事更细腻",
                "复杂指令遵循与结构化输出更稳",
                "速度偏慢、适合质量优先的任务",
            ]
        elif is_lightweight:
            speed, quality = "快", "中等"
            tasks = []
            strengths = [
                "推理快、吞吐高、成本低",
                "适合大批量辅助任务（校验/润色）",
                "适合作为通用兜底源",
            ]
        else:
            speed, quality = "中等", "中上"
            tasks = list(WRITING_TASKS)
            strengths = [
                "速度与质量较为均衡",
                "适合章节正文与人物等主力任务",
                "批量生成性价比好",
            ]

    if lat:
        speed = f"{speed}（{lat}）"

    # 通用兜底判定：轻量模型，或没有任何专属任务推荐时，建议作为通用兜底源
    recommend_as_fallback = is_lightweight or not tasks

    # 综合中文总述
    summary = (
        f"{model_label}：模型族为{family}，参数量级 {scale}，"
        f"速度评级「{speed}」，质量评级「{quality}」。"
        f"主要特点：{'；'.join(strengths)}。"
    )

    # 配置建议
    if tasks:
        task_text = "、".join(TASK_LABELS.get(t, t) for t in tasks)
        advice = (
            f"建议勾选「适用任务」为：{task_text}。"
            f"这样该模型只在上述任务被调用，避免被其它任务占用额度；"
            f"同时请把优先级(priority)设为较小值（如 1~5），以保证在同任务候选中被优先尝试。"
        )
    else:
        advice = (
            "建议不勾选任何「适用任务」，把它作为「通用兜底源」："
            "所有任务在专属源全部失败时才会回退到它。"
            "请把优先级(priority)设为较大值（如 90~99），避免它抢占专属源的顺位。"
        )

    if recommend_as_fallback and tasks:
        advice += " 另外它也可以不勾选任务作为兜底使用，视你的额度情况取舍。"

    return ModelProfile(
        model_name=raw_name,
        family=family,
        scale=scale,
        speed=speed,
        quality=quality,
        is_reasoning=is_reasoning,
        is_lightweight=is_lightweight,
        is_flagship=is_flagship,
        strengths=strengths,
        recommended_tasks=tasks,
        recommend_as_fallback=recommend_as_fallback,
        summary=summary,
        advice=advice,
        matched_by=matched_by,
    )
