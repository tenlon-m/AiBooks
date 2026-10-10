"""模型特点对话框 - 展示测试连接得到的模型中文特点，并支持一键应用推荐任务标签.

用户在"AI源配置页"点击【测试连接】后弹出本对话框：
- 展示模型族 / 参数量级 / 速度 / 质量 / 主要特点 / 配置建议
- 预勾选推荐"适用任务"，用户可自行增减后点击【应用任务标签】写回该 AI 源
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.ui.widgets.ai_source_edit_dialog import TASK_OPTIONS


class ModelProfileDialog(QDialog):
    """测试连接结果 + 模型特点说明 + 任务标签应用."""

    # 携带用户勾选的任务标签(module 名列表)
    apply_requested = Signal(list)

    def __init__(
        self,
        source_name: str,
        success: bool,
        message: str,
        latency_ms: int | None,
        profile: dict | None,
        current_tasks: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_name = source_name
        self._success = success
        self._message = message
        self._latency_ms = latency_ms
        self._profile = profile or {}
        self._current_tasks: set[str] = set(current_tasks or [])
        self._task_checks: dict[str, QCheckBox] = {}
        self.setWindowTitle("测试连接 - 模型特点")
        self.setMinimumWidth(560)
        self._init_ui()

    # ---------- UI ----------

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)

        title = QLabel(f"模型特点：{self._source_name}")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 4px;")
        outer.addWidget(title)

        status_text, status_color = self._status_line()
        status_label = QLabel(status_text)
        status_label.setWordWrap(True)
        status_label.setStyleSheet(f"color: {status_color}; padding: 4px; font-size: 12px;")
        outer.addWidget(status_label)

        # 可滚动内容区：模型信息较多，避免小屏被撑爆
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        if self._profile:
            layout.addWidget(self._build_summary())
            layout.addWidget(self._build_facts())
            layout.addWidget(self._build_strengths())
            layout.addWidget(self._build_tasks())
            layout.addWidget(self._build_advice())
        else:
            no_info = QLabel("（未获得模型特点信息）")
            no_info.setStyleSheet("color: #999;")
            layout.addWidget(no_info)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.apply_btn = QPushButton("应用勾选的任务标签")
        self.apply_btn.setStyleSheet(
            "background-color: #4caf50; color: white; padding: 6px 18px; border-radius: 4px;"
        )
        self.apply_btn.setEnabled(bool(self._profile))
        self.apply_btn.clicked.connect(self._on_apply)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(close_btn)
        outer.addLayout(btn_layout)

    def _status_line(self) -> tuple[str, str]:
        lat = f"实测耗时 {self._latency_ms} ms" if self._latency_ms is not None else ""
        if self._success:
            text = "连接测试：成功 ✓"
            if lat:
                text += f"（{lat}）"
            return text, "#2e7d32"
        text = f"连接测试：失败 ✗  {self._message}"
        if lat:
            text += f"（{lat}）"
        text += "\n提示：连接失败不影响查看下方模型特点，可据此判断该模型是否值得排查后使用。"
        return text, "#c62828"

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; padding: 6px 0 2px 0;")
        return label

    def _build_summary(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section_title("综合说明"))
        summary = QLabel(self._profile.get("summary", ""))
        summary.setWordWrap(True)
        summary.setStyleSheet(
            "background:#f5f7fa; border:1px solid #e0e6ed; border-radius:4px; padding:8px;"
        )
        layout.addWidget(summary)
        return box

    def _build_facts(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section_title("基本信息"))
        form = QFormLayout()
        matched_by = self._profile.get("matched_by", "heuristic")
        matched_text = "已知模型精确识别" if matched_by == "known" else "按模型名启发式推断"
        rows = [
            ("模型族：", self._profile.get("family", "-")),
            ("参数量级：", self._profile.get("scale", "-")),
            ("速度评级：", self._profile.get("speed", "-")),
            ("质量评级：", self._profile.get("quality", "-")),
            ("模型定位：", self._profile.get("positioning", "-")),
            ("识别方式：", matched_text),
        ]
        for label, value in rows:
            form.addRow(label, QLabel(str(value)))
        layout.addLayout(form)
        return box

    def _build_strengths(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section_title("主要特点"))
        strengths = self._profile.get("strengths") or []
        if not strengths:
            layout.addWidget(QLabel("（无）"))
        for s in strengths:
            item = QLabel(f"• {s}")
            item.setWordWrap(True)
            layout.addWidget(item)
        return box

    def _build_tasks(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section_title("适用任务（勾选后该源仅服务于这些任务）"))

        recommended = set(self._profile.get("recommended_tasks") or [])
        tip = QLabel(
            "以下为系统推荐，可自行调整。全部不勾选 = 通用兜底源（适用于全部任务）。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#666; font-size:11px;")
        layout.addWidget(tip)

        grid = QWidget()
        grid_layout = QVBoxLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        for i, (code, label) in enumerate(TASK_OPTIONS):
            cb = QCheckBox(f"{label} ({code})")
            # 默认勾选：优先沿用该源已配置的任务，其次采用系统推荐
            if self._current_tasks:
                cb.setChecked(code in self._current_tasks)
            else:
                cb.setChecked(code in recommended)
            cb.stateChanged.connect(self._update_fallback_hint)
            self._task_checks[code] = cb
            row_layout.addWidget(cb)
            if (i + 1) % 3 == 0:
                row_layout.addStretch()
                grid_layout.addWidget(row_widget)
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(12)
        row_layout.addStretch()
        grid_layout.addWidget(row_widget)
        layout.addWidget(grid)

        self.fallback_hint = QLabel("")
        self.fallback_hint.setStyleSheet("color:#4caf50; font-size:11px;")
        self.fallback_hint.setWordWrap(True)
        layout.addWidget(self.fallback_hint)
        self._update_fallback_hint()
        return box

    def _build_advice(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._section_title("配置建议"))
        advice = QLabel(self._profile.get("advice", ""))
        advice.setWordWrap(True)
        advice.setStyleSheet(
            "background:#fffbe6; border:1px solid #ffe58f; border-radius:4px; padding:8px;"
        )
        layout.addWidget(advice)
        return box

    # ---------- 交互 ----------

    def _update_fallback_hint(self) -> None:
        if not hasattr(self, "fallback_hint"):
            return
        if any(cb.isChecked() for cb in self._task_checks.values()):
            self.fallback_hint.setText("")
        else:
            self.fallback_hint.setText(
                "✓ 当前为通用兜底源：适用于全部任务，可作为所有任务的最后兜底候选"
            )

    def _on_apply(self) -> None:
        selected = [code for code, cb in self._task_checks.items() if cb.isChecked()]
        self.apply_requested.emit(selected)
        self.accept()
