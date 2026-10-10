"""AI源编辑对话框 - 编辑已添加AI源的所有字段，保存后发射saved信号."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker


# 已知任务标签清单（与 gateway.call(module=...) 的 module 名对应）
# 勾选后该源将专门服务于这些任务；不勾选任意任务 = 通用兜底源，适用于全部任务。
TASK_OPTIONS: list[tuple[str, str]] = [
    ("outline", "大纲生成/校验"),
    ("writing", "章节正文"),
    ("character", "人物管理"),
    ("hook", "爽点/钩子"),
    ("validation", "内容校验"),
    ("polish", "润色"),
    ("style", "风格库"),
]


class AiSourceEditDialog(QDialog):
    """编辑已添加AI源的模态对话框.

    保存成功后发射 saved 信号（携带 source_id），调用方可据此刷新列表并触发自动测试。
    API Key 密文显示且不回显原值，留空表示不修改。
    Ollama 类型时模型字段为下拉列表，自动加载已安装模型并回显当前模型。
    """

    saved = Signal(str)

    def __init__(self, source_data: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_data = source_data
        self._source_id: str = source_data.get("source_id", "")
        self._workers: list[ApiWorker] = []
        self._pending_model_select: str | None = None
        self.setWindowTitle("编辑AI源")
        self.setMinimumWidth(480)
        self._init_ui()
        self._fill_fields()

    def _add_worker(self, worker) -> None:
        """注册 ApiWorker 并在完成后自动清理."""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()


    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("编辑AI源配置")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("AI源名称（1-50字符）")
        form.addRow("名称：", self.name_input)

        self.type_combo = QComboBox()
        self.type_combo.addItem("在线OpenAI兼容", "online_openai_compatible")
        self.type_combo.addItem("本地Ollama", "local_ollama")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("类型：", self.type_combo)

        self.endpoint_input = QLineEdit()
        self.endpoint_input.setPlaceholderText("http://localhost:11434/v1")
        form.addRow("API地址：", self.endpoint_input)

        self.model_stack = QStackedWidget()
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("模型名称")
        self.model_stack.addWidget(self.model_input)

        ollama_model_widget = QWidget()
        ollama_model_layout = QHBoxLayout(ollama_model_widget)
        ollama_model_layout.setContentsMargins(0, 0, 0, 0)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(False)
        ollama_model_layout.addWidget(self.model_combo, 1)
        self.refresh_models_btn = QPushButton("刷新")
        self.refresh_models_btn.clicked.connect(self._fetch_ollama_models)
        ollama_model_layout.addWidget(self.refresh_models_btn)
        self.model_stack.addWidget(ollama_model_widget)
        form.addRow("模型：", self.model_stack)

        self.apikey_input = QLineEdit()
        self.apikey_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.apikey_input.setPlaceholderText("留空表示不修改原值")
        apikey_widget = QWidget()
        apikey_layout = QHBoxLayout(apikey_widget)
        apikey_layout.setContentsMargins(0, 0, 0, 0)
        apikey_layout.addWidget(self.apikey_input, 1)
        self.apikey_toggle_btn = QPushButton("显示")
        self.apikey_toggle_btn.setFixedWidth(60)
        self.apikey_toggle_btn.clicked.connect(self._toggle_apikey_visibility)
        apikey_layout.addWidget(self.apikey_toggle_btn)
        self.apikey_view_btn = QPushButton("查看已保存")
        self.apikey_view_btn.setFixedWidth(90)
        self.apikey_view_btn.clicked.connect(self._view_saved_apikey)
        apikey_layout.addWidget(self.apikey_view_btn)
        form.addRow("API Key：", apikey_widget)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 100)
        self.priority_spin.setToolTip(
            '优先级：数字越小优先级越高。路由策略为"故障转移"时，按优先级从小到大依次尝试；为"手动指定"时，直接使用指定源。'
        )
        form.addRow("优先级：", self.priority_spin)

        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(1, 100)
        self.weight_spin.setToolTip(
            '权重：路由策略为"负载均衡"时，按权重比例分配请求到各AI源。权重越大，分到的请求越多。例如源A权重3、源B权重1，则A分到75%请求、B分到25%。'
        )
        form.addRow("权重：", self.weight_spin)

        self.enabled_check = QCheckBox("启用此AI源")
        form.addRow("", self.enabled_check)

        self.task_checks: dict[str, QCheckBox] = {}
        task_widget = QWidget()
        task_layout = QVBoxLayout(task_widget)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.setSpacing(4)
        task_help = QLabel("勾选后该源仅服务于指定任务；全部不勾选 = 通用兜底源（适用于全部任务）")
        task_help.setStyleSheet("color: #666; font-size: 11px;")
        task_layout.addWidget(task_help)
        self.task_universal_hint = QLabel("")
        self.task_universal_hint.setStyleSheet("color: #4caf50; font-size: 11px;")
        task_layout.addWidget(self.task_universal_hint)
        checks_row = QWidget()
        checks_layout = QHBoxLayout(checks_row)
        checks_layout.setContentsMargins(0, 0, 0, 0)
        checks_layout.setSpacing(12)
        for code, label in TASK_OPTIONS:
            cb = QCheckBox(f"{label} ({code})")
            cb.stateChanged.connect(self._update_task_hint)
            self.task_checks[code] = cb
            checks_layout.addWidget(cb)
        checks_layout.addStretch()
        task_layout.addWidget(checks_row)
        form.addRow("适用任务：", task_widget)

        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = QPushButton("保存")
        self.save_btn.setStyleSheet("background-color: #4caf50; color: white; padding: 6px 20px; border-radius: 4px;")
        self.save_btn.clicked.connect(self._on_save)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def _fill_fields(self) -> None:
        d = self._source_data
        self.name_input.setText(d.get("name", ""))
        source_type = d.get("source_type", "")
        idx = self.type_combo.findData(source_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.endpoint_input.setText(d.get("api_endpoint", ""))
        self._pending_model_select = d.get("model_name", "")
        if source_type == "local_ollama":
            self.model_stack.setCurrentIndex(1)
            self._fetch_ollama_models()
        else:
            self.model_stack.setCurrentIndex(0)
            self.model_input.setText(d.get("model_name", ""))
        self.apikey_input.clear()
        self.priority_spin.setValue(d.get("priority", 1))
        self.weight_spin.setValue(d.get("weight", 1))
        self.enabled_check.setChecked(d.get("enabled", True))
        # 回填适用任务：后端返回 task_tags 字段（list[str]，每个元素为 module 名）
        selected_tasks = set(d.get("task_tags") or [])
        for code, cb in self.task_checks.items():
            cb.blockSignals(True)
            cb.setChecked(code in selected_tasks)
            cb.blockSignals(False)
        self._update_task_hint()

    def _on_type_changed(self) -> None:
        source_type = self.type_combo.currentData()
        if source_type == "local_ollama":
            self.model_stack.setCurrentIndex(1)
            self._fetch_ollama_models()
        else:
            self.model_stack.setCurrentIndex(0)

    def _fetch_ollama_models(self) -> None:
        endpoint = self.endpoint_input.text().strip()
        if not endpoint:
            return
        self.refresh_models_btn.setEnabled(False)
        self.model_combo.clear()
        self.model_combo.addItem("加载中...", None)
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/config/ollama/models", params={"endpoint": endpoint})
        worker.result.connect(self._on_ollama_models_loaded)
        worker.error.connect(self._on_ollama_models_error)
        self._add_worker(worker)
        worker.start()

    def _on_ollama_models_loaded(self, data: dict) -> None:
        self.refresh_models_btn.setEnabled(True)
        if self.type_combo.currentData() != "local_ollama":
            return
        self.model_combo.clear()
        models = data.get("models", [])
        error = data.get("error")
        if error and not models:
            self.status_label.setText(error)
            QMessageBox.warning(self, "提示", error)
            return
        for m in models:
            self.model_combo.addItem(m, m)
        if self._pending_model_select:
            idx = self.model_combo.findData(self._pending_model_select)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.status_label.setText(f"当前模型'{self._pending_model_select}'可能已被卸载，请重新选择")
            self._pending_model_select = None
        self.status_label.setText(f"已获取 {len(models)} 个本地模型")

    def _on_ollama_models_error(self, msg: str) -> None:
        self.refresh_models_btn.setEnabled(True)
        self.model_combo.clear()
        self.status_label.setText(f"获取模型列表失败：{msg}")

    def _get_current_model_name(self) -> str:
        if self.type_combo.currentData() == "local_ollama":
            return self.model_combo.currentData() or ""
        return self.model_input.text().strip()

    def _update_task_hint(self) -> None:
        """根据勾选情况更新底部提示."""
        any_checked = any(cb.isChecked() for cb in self.task_checks.values())
        if any_checked:
            self.task_universal_hint.setText("")
        else:
            self.task_universal_hint.setText("✓ 当前为通用兜底源：适用于全部任务，可作为所有任务的最后兜底候选")

    def _collect_payload(self) -> dict:
        payload: dict = {
            "name": self.name_input.text().strip(),
            "source_type": self.type_combo.currentData(),
            "api_endpoint": self.endpoint_input.text().strip(),
            "model_name": self._get_current_model_name(),
            "priority": self.priority_spin.value(),
            "weight": self.weight_spin.value(),
            "enabled": self.enabled_check.isChecked(),
            "task_tags": [code for code, cb in self.task_checks.items() if cb.isChecked()],
        }
        api_key = self.apikey_input.text().strip()
        if api_key:
            payload["api_key"] = api_key
        return payload

    def _validate(self) -> bool:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "提示", "请输入名称")
            return False
        if not self.endpoint_input.text().strip():
            QMessageBox.warning(self, "提示", "请输入API地址")
            return False
        if not self._get_current_model_name():
            QMessageBox.warning(self, "提示", "请选择或输入模型名称")
            return False
        return True

    def _toggle_apikey_visibility(self) -> None:
        if self.apikey_input.echoMode() == QLineEdit.EchoMode.Password:
            self.apikey_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.apikey_toggle_btn.setText("隐藏")
        else:
            self.apikey_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.apikey_toggle_btn.setText("显示")

    def _view_saved_apikey(self) -> None:
        self.apikey_view_btn.setEnabled(False)
        self.status_label.setText("正在获取已保存的 API Key...")
        client = get_api_client()
        worker = ApiWorker(client.get, f"/api/config/ai_sources/{self._source_id}/key")
        worker.result.connect(self._on_saved_key_loaded)
        worker.error.connect(self._on_saved_key_error)
        self._add_worker(worker)
        worker.start()

    def _on_saved_key_loaded(self, data: dict) -> None:
        self.apikey_view_btn.setEnabled(True)
        key = data.get("api_key")
        if key:
            self.apikey_input.setText(key)
            self.apikey_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.apikey_toggle_btn.setText("隐藏")
            self.status_label.setText("已加载已保存的 API Key（修改后点保存生效）")
        else:
            self.status_label.setText("该AI源未保存 API Key（如为本地Ollama则无需填写）")

    def _on_saved_key_error(self, msg: str) -> None:
        self.apikey_view_btn.setEnabled(True)
        self.status_label.setText(f"获取 API Key 失败：{msg}")
        QMessageBox.warning(self, "提示", f"获取已保存的 API Key 失败：\n{msg}")

    def _on_save(self) -> None:
        if not self._validate():
            return
        payload = self._collect_payload()
        self.save_btn.setEnabled(False)
        self.status_label.setText("保存中...")
        client = get_api_client()
        worker = ApiWorker(client.put, f"/api/config/ai_sources/{self._source_id}", json=payload)
        worker.result.connect(self._on_saved)
        worker.error.connect(self._on_save_error)
        self._add_worker(worker)
        worker.start()

    def _on_saved(self, data: dict) -> None:
        self.save_btn.setEnabled(True)
        self.status_label.setText("保存成功")
        self.saved.emit(self._source_id)
        self.accept()

    def _on_save_error(self, msg: str) -> None:
        self.save_btn.setEnabled(True)
        self.status_label.setText(f"保存失败：{msg}")
        QMessageBox.critical(self, "错误", f"保存失败：{msg}")
