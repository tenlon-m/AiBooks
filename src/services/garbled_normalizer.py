"""统一字符规范化机制 - 全部覆盖场景共用，纯本地确定性计算.

支持任意文本字段：chapter.content / synopsis_points / content_desc /
hook_content / synopsis.content / worldview.content 等。

对应 spec 5.1.1 业务规则与 design 2.2.2.1 接口设计。
"""
from __future__ import annotations

import re
from typing import NamedTuple

from loguru import logger
from pydantic import BaseModel, Field


class GarbledConfig(BaseModel):
    """乱码修复配置 - 判定阈值集合."""

    enabled: bool = True
    max_blank_lines: int = 1
    max_punct_repeat: int = 2
    max_consecutive_spaces: int = 1
    enable_fullwidth_indent: bool = True
    enable_punct_repeat_fix: bool = True
    enable_whitespace_cleanup: bool = True
    enable_irreversible_clear: bool = True


class GarbledDetailItem(BaseModel):
    """单条修复明细."""

    category: str = ""
    position: str = ""
    action: str = ""
    irreversible: bool = False


class CharacterRepairStat(BaseModel):
    """字符修复统计."""

    garbled_detected: int = 0
    format_detected: int = 0
    garbled_fixed: int = 0
    format_fixed: int = 0
    remainder: int = 0
    hit_categories: list[str] = Field(default_factory=list)
    irreversible_cleared: int = 0
    details: list[GarbledDetailItem] = Field(default_factory=list)


class GarbledIssue(BaseModel):
    """检测问题（仅检测不修复时返回）."""

    category: str = ""
    level: str = ""
    position: str = ""
    suggestion: str = ""


# ── 字符类别常量 ──────────────────────────────────────────────
_CONTROL_CHARS = set(chr(i) for i in range(0x00, 0x20)) | set(chr(i) for i in range(0x7F, 0xA0))
_CONTROL_CHARS.discard("\n")  # 合法换行豁免
_ZERO_WIDTH_CHARS = {"\u200b", "\u200c", "\u200d", "\ufeff", "\u00ad"}
_REPLACEMENT_CHAR = "\ufffd"
_PUA_RANGE = set(chr(i) for i in range(0xE000, 0xF900))
_FULLWIDTH_SPACE = "\u3000"
_NBSP = "\u00a0"
_TAB = "\t"

# 合法多字符标点豁免
_ELLIPSIS_CHARS = {"…", "．"}
_DASH_CHARS = {"—", "–"}

# 中文标点集合（用于重复检测）
_CN_PUNCT = set("。，、；：？！「」『』《》〈〉（）【】…—·．~\"'")

# 连续异常高位字符序列正则（非中文/英文/数字/常用标点/常用空白的连续序列）
_NORMAL_CHARS = re.compile(
    r"[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
    r"a-zA-Z0-9"
    r"\s\n\r\t"
    r"。，、；：？！「」『』《》〈〉（）【】…—·．~\"'`@#$%^&*+=|\\/<>\[\]{}_-]+"
)


class _ScanResult(NamedTuple):
    """单遍扫描结果."""

    text: str
    garbled_count: int
    format_count: int
    irreversible: int
    details: list[GarbledDetailItem]
    categories: set[str]


class GarbledNormalizer:
    """统一字符规范化机制."""

    def detect_and_normalize(
        self,
        text: str,
        config: GarbledConfig,
    ) -> tuple[str, CharacterRepairStat]:
        """检测并规范化文本.

        前置条件: text 为字符串（可为空），config 为已解析的生效配置
        后置条件: 返回(规范化后文本, 统计)；规范化失败时回退原文
        异常映射: 内部异常捕获后回退原文，stat.remainder 标记异常
        """
        empty_stat = CharacterRepairStat()
        if not isinstance(text, str) or not text:
            return text, empty_stat
        if not config.enabled:
            return text, empty_stat

        try:
            result = self._normalize_impl(text, config)
            return result
        except Exception as e:
            logger.warning(f"乱码修复异常，返回原始文本: {e}")
            return text, empty_stat

    def detect_only(
        self,
        text: str,
        config: GarbledConfig,
    ) -> list[GarbledIssue]:
        """仅检测不修复，返回问题列表（校验场景用）.

        前置条件: text 为字符串，config 为已解析的生效配置
        后置条件: 返回问题列表，每项含类别/级别/位置/建议
        异常映射: 内部异常返回空列表
        """
        if not isinstance(text, str) or not text:
            return []
        if not config.enabled:
            return []

        try:
            return self._detect_impl(text, config)
        except Exception as e:
            logger.warning(f"乱码检测异常，返回空列表: {e}")
            return []

    # ── 内部实现 ──────────────────────────────────────────────

    def _normalize_impl(
        self, text: str, config: GarbledConfig
    ) -> tuple[str, CharacterRepairStat]:
        """规范化实现：三遍扫描."""
        details: list[GarbledDetailItem] = []
        categories: set[str] = set()
        garbled_count = 0
        format_count = 0
        irreversible = 0

        # 第一遍：字符乱码检测与修复
        r1 = self._scan_garbled(text, config)
        text = r1.text
        garbled_count += r1.garbled_count
        irreversible += r1.irreversible
        details.extend(r1.details)
        categories.update(r1.categories)

        # 第二遍：格式错乱检测与修复
        r2 = self._scan_format(text, config)
        text = r2.text
        format_count += r2.format_count
        details.extend(r2.details)
        categories.update(r2.categories)

        # 第三遍：乱码符号序列检测与修复
        r3 = self._scan_garbled_sequence(text, config)
        text = r3.text
        garbled_count += r3.garbled_count
        details.extend(r3.details)
        categories.update(r3.categories)

        stat = CharacterRepairStat(
            garbled_detected=garbled_count,
            format_detected=format_count,
            garbled_fixed=garbled_count,
            format_fixed=format_count,
            remainder=0,
            hit_categories=sorted(categories),
            irreversible_cleared=irreversible,
            details=details,
        )
        return text, stat

    def _detect_impl(
        self, text: str, config: GarbledConfig
    ) -> list[GarbledIssue]:
        """仅检测实现：复用扫描逻辑但不修改正文."""
        issues: list[GarbledIssue] = []

        # 第一遍：字符乱码检测
        r1 = self._scan_garbled(text, config)
        for d in r1.details:
            level = "一般" if d.irreversible else "轻微"
            issues.append(GarbledIssue(
                category=d.category,
                level=level,
                position=d.position,
                suggestion=d.action,
            ))

        # 第二遍：格式错乱检测
        r2 = self._scan_format(text, config)
        for d in r2.details:
            issues.append(GarbledIssue(
                category=d.category,
                level="轻微",
                position=d.position,
                suggestion=d.action,
            ))

        # 第三遍：乱码符号序列检测
        r3 = self._scan_garbled_sequence(text, config)
        for d in r3.details:
            issues.append(GarbledIssue(
                category=d.category,
                level="一般",
                position=d.position,
                suggestion=d.action,
            ))

        return issues

    # ── 第一遍：字符乱码扫描 ──────────────────────────────────

    def _scan_garbled(
        self, text: str, config: GarbledConfig
    ) -> _ScanResult:
        """扫描并修复字符乱码（控制字符/零宽/U+FFFD/私用区）."""
        details: list[GarbledDetailItem] = []
        categories: set[str] = set()
        garbled_count = 0
        irreversible = 0
        result_chars: list[str] = []

        for i, ch in enumerate(text):
            if ch in _CONTROL_CHARS:
                garbled_count += 1
                categories.add("控制字符")
                details.append(GarbledDetailItem(
                    category="控制字符",
                    position=f"位置{i}",
                    action="删除控制字符",
                ))
                continue
            if ch in _ZERO_WIDTH_CHARS:
                garbled_count += 1
                categories.add("零宽字符")
                details.append(GarbledDetailItem(
                    category="零宽字符",
                    position=f"位置{i}",
                    action="删除零宽字符",
                ))
                continue
            if ch == _REPLACEMENT_CHAR:
                garbled_count += 1
                irreversible += 1
                categories.add("替换字符")
                if config.enable_irreversible_clear:
                    details.append(GarbledDetailItem(
                        category="替换字符",
                        position=f"位置{i}",
                        action="清除不可逆乱码(U+FFFD)",
                        irreversible=True,
                    ))
                    continue
                else:
                    result_chars.append(ch)
                    continue
            if ch in _PUA_RANGE:
                garbled_count += 1
                categories.add("私用区字符")
                details.append(GarbledDetailItem(
                    category="私用区字符",
                    position=f"位置{i}",
                    action="删除私用区字符",
                ))
                continue
            result_chars.append(ch)

        return _ScanResult(
            text="".join(result_chars),
            garbled_count=garbled_count,
            format_count=0,
            irreversible=irreversible,
            details=details,
            categories=categories,
        )

    # ── 第二遍：格式错乱扫描 ──────────────────────────────────

    def _scan_format(
        self, text: str, config: GarbledConfig
    ) -> _ScanResult:
        """扫描并修复格式错乱（空行/空白/标点重复/全角缩进）."""
        if not config.enable_whitespace_cleanup and not config.enable_punct_repeat_fix:
            return _ScanResult(text, 0, 0, 0, [], set())

        details: list[GarbledDetailItem] = []
        categories: set[str] = set()
        format_count = 0

        lines = text.split("\n")
        processed_lines: list[str] = []

        for line in lines:
            processed, fc, d, c = self._fix_line_format(line, config, format_count)
            processed_lines.append(processed)
            format_count = fc
            details.extend(d)
            categories.update(c)

        # 连续空行压缩
        if config.enable_whitespace_cleanup:
            compressed, fc, d = self._compress_blank_lines(
                processed_lines, config.max_blank_lines
            )
            format_count += fc
            details.extend(d)
            if fc > 0:
                categories.add("连续空行")
            processed_lines = compressed

        result = "\n".join(processed_lines)
        return _ScanResult(
            text=result,
            garbled_count=0,
            format_count=format_count,
            irreversible=0,
            details=details,
            categories=categories,
        )

    def _fix_line_format(
        self, line: str, config: GarbledConfig, base_count: int
    ) -> tuple[str, int, list[GarbledDetailItem], set[str]]:
        """修复单行格式问题."""
        details: list[GarbledDetailItem] = []
        categories: set[str] = set()
        count = base_count
        original = line

        if not config.enable_whitespace_cleanup:
            return line, count, details, categories

        # 制表符去除
        if _TAB in line:
            tab_count = line.count(_TAB)
            line = line.replace(_TAB, "")
            count += tab_count
            categories.add("制表符")
            details.append(GarbledDetailItem(
                category="制表符",
                position=f"本行含{tab_count}个制表符",
                action="去除制表符",
            ))

        # 非断行空格替换
        if _NBSP in line:
            nbsp_count = line.count(_NBSP)
            line = line.replace(_NBSP, " ")
            count += nbsp_count
            categories.add("非断行空格")
            details.append(GarbledDetailItem(
                category="非断行空格",
                position=f"本行含{nbsp_count}个非断行空格",
                action="替换为普通空格",
            ))

        # 全角空格处理：仅段首保留2个，非行首删除
        if _FULLWIDTH_SPACE in line:
            line, fw_count = self._fix_fullwidth_spaces(line, config)
            if fw_count > 0:
                count += fw_count
                categories.add("全角空格")
                details.append(GarbledDetailItem(
                    category="全角空格",
                    position=f"本行规整{fw_count}处全角空格",
                    action="全角空格缩进规整",
                ))

        # 行首行尾冗余空白去除
        stripped = line.strip(" \r")
        if stripped != line:
            count += 1
            categories.add("行首行尾空白")
            details.append(GarbledDetailItem(
                category="行首行尾空白",
                position="本行首尾",
                action="去除行首行尾冗余空白",
            ))
            line = stripped

        # 段落内连续空格压缩
        if config.max_consecutive_spaces >= 0:
            max_spaces = config.max_consecutive_spaces
            pattern = re.compile(r" {" + str(max_spaces + 1) + r",}")
            if pattern.search(line):
                replacement = " " * max_spaces if max_spaces > 0 else ""
                new_line = pattern.sub(replacement, line)
                if new_line != line:
                    count += 1
                    categories.add("连续空格")
                    details.append(GarbledDetailItem(
                        category="连续空格",
                        position="本行内",
                        action=f"压缩连续空格至{max_spaces}个",
                    ))
                    line = new_line

        # 重复标点压缩
        if config.enable_punct_repeat_fix:
            line, pc, pd = self._fix_punct_repeat(line, config.max_punct_repeat)
            count += pc
            details.extend(pd)
            if pc > 0:
                categories.add("重复标点")

        return line, count, details, categories

    def _fix_fullwidth_spaces(
        self, line: str, config: GarbledConfig
    ) -> tuple[str, int]:
        """处理全角空格：段首保留2个，非行首删除."""
        if not config.enable_fullwidth_indent:
            count = line.count(_FULLWIDTH_SPACE)
            return line.replace(_FULLWIDTH_SPACE, ""), count

        # 统计全角空格数量
        count = 0
        # 检查行首是否以全角空格开头
        stripped = line.lstrip(_FULLWIDTH_SPACE)
        leading_count = len(line) - len(stripped)

        if leading_count > 0:
            # 段首缩进：统一为2个全角空格
            if leading_count != 2:
                count += 1
                line = _FULLWIDTH_SPACE * 2 + stripped
            # 非行首的全角空格删除
            rest_count = stripped.count(_FULLWIDTH_SPACE)
            if rest_count > 0:
                count += rest_count
                line = line[:2] + stripped.replace(_FULLWIDTH_SPACE, "")
        else:
            # 无行首全角空格，删除所有全角空格
            rest_count = line.count(_FULLWIDTH_SPACE)
            if rest_count > 0:
                count += rest_count
                line = line.replace(_FULLWIDTH_SPACE, "")

        return line, count

    def _fix_punct_repeat(
        self, line: str, max_repeat: int
    ) -> tuple[str, int, list[GarbledDetailItem]]:
        """压缩连续重复标点，省略号/破折号豁免."""
        details: list[GarbledDetailItem] = []
        count = 0
        if max_repeat <= 0:
            return line, count, details

        result: list[str] = []
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            if ch in _CN_PUNCT or (ch in _ELLIPSIS_CHARS or ch in _DASH_CHARS):
                # 收集连续相同字符
                j = i + 1
                while j < n and line[j] == ch:
                    j += 1
                run_len = j - i

                # 豁免：省略号「……」和破折号「——」
                if ch in _ELLIPSIS_CHARS or ch in _DASH_CHARS:
                    result.append(line[i:j])
                    i = j
                    continue

                if run_len > max_repeat:
                    count += 1
                    details.append(GarbledDetailItem(
                        category="重复标点",
                        position=f"字符'{ch}'连续{run_len}次",
                        action=f"压缩至{max_repeat}次",
                    ))
                    result.append(ch * max_repeat)
                else:
                    result.append(line[i:j])
                i = j
            else:
                result.append(ch)
                i += 1

        return "".join(result), count, details

    def _compress_blank_lines(
        self, lines: list[str], max_blank: int
    ) -> tuple[list[str], int, list[GarbledDetailItem]]:
        """压缩连续空行."""
        details: list[GarbledDetailItem] = []
        count = 0
        if max_blank < 0:
            return lines, count, details

        result: list[str] = []
        blank_run = 0
        for line in lines:
            if line.strip() == "":
                blank_run += 1
                if blank_run <= max_blank + 1:
                    result.append(line)
                else:
                    if blank_run == max_blank + 2:
                        count += 1
                        details.append(GarbledDetailItem(
                            category="连续空行",
                            position=f"第{len(result)}行附近",
                            action=f"压缩连续空行至{max_blank}个",
                        ))
            else:
                blank_run = 0
                result.append(line)

        return result, count, details

    # ── 第三遍：乱码符号序列扫描 ──────────────────────────────

    def _scan_garbled_sequence(
        self, text: str, config: GarbledConfig
    ) -> _ScanResult:
        """扫描连续异常高位字符序列（乱码符号序列）."""
        details: list[GarbledDetailItem] = []
        categories: set[str] = set()
        count = 0

        matches = list(_NORMAL_CHARS.finditer(text))
        if not matches:
            return _ScanResult(text, 0, 0, 0, [], set())

        # 合并连续的异常序列
        result: list[str] = []
        last_end = 0
        for m in matches:
            seq = m.group()
            if len(seq) >= 2:
                result.append(text[last_end:m.start()])
                count += 1
                categories.add("乱码符号序列")
                details.append(GarbledDetailItem(
                    category="乱码符号序列",
                    position=f"位置{m.start()}-{m.end()}",
                    action="清除乱码符号序列",
                ))
                last_end = m.end()
            else:
                pass

        result.append(text[last_end:])
        new_text = "".join(result)

        return _ScanResult(
            text=new_text,
            garbled_count=count,
            format_count=0,
            irreversible=0,
            details=details,
            categories=categories,
        )