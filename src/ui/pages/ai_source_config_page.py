"""AI源配置页 - 预设国内免费中文大模型 + 增删改查AI源 + 测试连接 + 路由策略."""
from __future__ import annotations


from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.widgets.ai_source_edit_dialog import AiSourceEditDialog
from src.ui.widgets.model_profile_dialog import ModelProfileDialog
from src.ui.theme.theme_qss_builder import apply_theme_variant


# 预设模型说明：
# - task_tags：推荐"适用任务"（空 = 通用兜底源，适用于全部任务）
# - priority ：推荐优先级；专属任务的源取小值(1~10)，通用兜底源取大值(90~99)，
#              避免兜底源在同一任务的候选集合里抢占专属源的顺位。
PRESET_MODELS = [
    {
        "name": "硅基流动-Qwen2.5-7B",
        "source_type": "online_openai_compatible",
        "api_endpoint": "https://api.siliconflow.cn/v1",
        "model_name": "Qwen/Qwen2.5-7B-Instruct",
        "tags": ["免费", "中文", "通义千问"],
        "task_tags": [],
        "priority": 90,
        "needs_api_key": True,
        "register_url": "https://cloud.siliconflow.cn/iSiliconFlow",
        "desc": "注册即送免费额度，Qwen2.5中文写作优秀。建议作为通用兜底源（不勾选任务）",
    },
    {
        "name": "硅基流动-Qwen2.5-14B",
        "source_type": "online_openai_compatible",
        "api_endpoint": "https://api.siliconflow.cn/v1",
        "model_name": "Qwen/Qwen2.5-14B-Instruct",
        "tags": ["免费", "中文", "通义千问"],
        "task_tags": ["writing", "character", "hook", "validation", "polish", "style"],
        "priority": 1,
        "needs_api_key": True,
        "register_url": "https://cloud.siliconflow.cn/iSiliconFlow",
        "desc": "Qwen2.5-14B，速度与质量平衡好，建议承担正文/人物/钩子等主力任务",
    },
    {
        "name": "DeepSeek-Chat",
        "source_type": "online_openai_compatible",
        "api_endpoint": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "tags": ["免费", "中文", "DeepSeek"],
        "task_tags": ["outline", "writing"],
        "priority": 5,
        "needs_api_key": True,
        "register_url": "https://platform.deepseek.com/api_keys",
        "desc": "DeepSeek-V3，中文写作极佳，价格极低；可同时承担大纲与正文",
    },
    {
        "name": "智谱GLM-4-Flash",
        "source_type": "online_openai_compatible",
        "api_endpoint": "https://open.bigmodel.cn/api/paas/v4",
        "model_name": "glm-4-flash",
        "tags": ["免费", "中文", "智谱"],
        "task_tags": [],
        "priority": 95,
        "needs_api_key": True,
        "register_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "desc": "GLM-4-Flash完全免费，响应快。建议作为跨厂商通用兜底源",
    },
    {
        "name": "阿里百炼-Qwen-Turbo",
        "source_type": "online_openai_compatible",
        "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_name": "qwen-turbo",
        "tags": ["免费", "中文", "通义千问"],
        "task_tags": [],
        "priority": 92,
        "needs_api_key": True,
        "register_url": "https://dashscope.console.aliyun.com/apiKey",
        "desc": "阿里云百炼，新用户免费额度。响应快，建议作为通用兜底源",
    },
    {
        "name": "月之暗面-Kimi",
        "source_type": "online_openai_compatible",
        "api_endpoint": "https://api.moonshot.cn/v1",
        "model_name": "moonshot-v1-8k",
        "tags": ["免费", "中文", "Kimi"],
        "task_tags": [],
        "priority": 50,
        "needs_api_key": True,
        "register_url": "https://platform.moonshot.cn/console/api-keys",
        "desc": "Kimi 8K 短上下文版，响应快；如需长上下文请改用 moonshot-v1-128k 并勾选大纲任务",
    },
    {
        "name": "硅基流动-Qwen2.5-32B",
        "source_type": "online_openai_compatible",
        "api_endpoint": "https://api.siliconflow.cn/v1",
        "model_name": "Qwen/Qwen2.5-32B-Instruct",
        "tags": ["免费", "中文", "大模型"],
        "task_tags": ["outline"],
        "priority": 1,
        "needs_api_key": True,
        "register_url": "https://cloud.siliconflow.cn/iSiliconFlow",
        "desc": "Qwen2.5-32B，中文写作质量最佳，速度偏慢；建议专门承担大纲生成（质量优先）",
    },
    {
        "name": "本地Ollama",
        "source_type": "local_ollama",
        "api_endpoint": "http://localhost:11434/v1",
        "model_name": "",
        "tags": ["本地", "免Key", "中文"],
        "task_tags": [],
        "priority": 10,
        "needs_api_key": False,
        "register_url": "https://ollama.com/download",
        "desc": "完全免费免API Key，需先安装Ollama并拉取模型，选中后自动获取已安装模型列表",
        "is_ollama_template": True,
    },
]


def _format_task_hint(task_tags: list[str]) -> str:
    """把任务标签列表格式化为中文提示."""
    from src.ai.model_profiler import TASK_LABELS

    if not task_tags:
        return "适用任务：通用兜底（适用于全部任务）"
    labels = "、".join(TASK_LABELS.get(t, t) for t in task_tags)
    return f"适用任务：{labels}"


class AiSourceConfigPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._sources_cache: list[dict] = []
        # 当前选中预设推荐的"适用任务"：添加时自动带入，避免用户漏配
        self._pending_preset_task_tags: list[str] = []
        self._init_ui()
        self._load_sources()
        self._load_policy()
        ctx = get_project_context()
        ctx.project_changed.connect(self._on_project_changed)

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


    def clear_page(self) -> None:
        self.preset_combo.setCurrentIndex(0)
        self.name_input.clear()
        self.endpoint_input.clear()
        self.model_input.clear()
        self.apikey_input.clear()
        self.priority_spin.setValue(1)
        self.weight_spin.setValue(1)
        self._pending_preset_task_tags = []
        self.status_label.clear()

    def has_unsaved_changes(self) -> bool:
        return False

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        pass


    def _on_type_changed(self) -> None:
        source_type = self.type_combo.currentData()
        if source_type == "local_ollama":
            self.model_stack.setCurrentIndex(1)
            self._fetch_ollama_models()
        else:
            self.model_stack.setCurrentIndex(0)

    def _toggle_config_section(self) -> None:
        visible = not self._config_container.isVisible()
        self._config_container.setVisible(visible)
        self._config_toggle_btn.setText(
            "▼ 添加/配置AI源（点击折叠）" if visible
            else "▶ 添加/配置AI源（点击展开）"
        )

    def _toggle_apikey_visibility(self) -> None:
        if self.apikey_input.echoMode() == QLineEdit.EchoMode.Password:
            self.apikey_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.apikey_toggle_btn.setText("隐藏")
        else:
            self.apikey_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.apikey_toggle_btn.setText("显示")

    def _on_refresh_models(self) -> None:
        self._fetch_ollama_models()

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
        if error:
            self.status_label.setText(error)
            if not models:
                QMessageBox.warning(self, "提示", error)
        else:
            for m in models:
                self.model_combo.addItem(m, m)
            self.status_label.setText(f"已获取 {len(models)} 个本地模型")

    def _on_ollama_models_error(self, msg: str) -> None:
        self.refresh_models_btn.setEnabled(True)
        self.model_combo.clear()
        self.status_label.setText(f"获取模型列表失败：{msg}")

    def _get_current_model_name(self) -> str:
        if self.type_combo.currentData() == "local_ollama":
            return self.model_combo.currentData() or ""
        return self.model_input.text().strip()

    def _on_preset_selected(self, index: int) -> None:
        if index <= 0:
            self.get_key_btn.setEnabled(False)
            self.preset_desc_label.setText("")
            self._pending_preset_task_tags = []
            return
        preset = self.preset_combo.itemData(index)
        if not preset:
            return
        self._pending_preset_task_tags = list(preset.get("task_tags") or [])
        self.name_input.setText(preset["name"])
        type_idx = self.type_combo.findData(preset["source_type"])
        if type_idx >= 0:
            self.type_combo.setCurrentIndex(type_idx)
        self.endpoint_input.setText(preset["api_endpoint"])
        if preset.get("is_ollama_template"):
            self.model_input.clear()
        else:
            self.model_input.setText(preset["model_name"])
        self.apikey_input.clear()
        # 预设同时给出推荐的优先级：专属任务源取小值、通用兜底源取大值
        self.priority_spin.setValue(int(preset.get("priority", 1)))
        needs_key = preset.get("needs_api_key", True)
        desc = preset.get("desc", "")
        url = preset.get("register_url", "")
        self.preset_desc_label.setText(f"说明：{desc}")
        task_hint = _format_task_hint(preset.get("task_tags") or [])
        if not needs_key:
            self.apikey_input.setPlaceholderText("本地模型无需API Key，可直接添加")
            self.get_key_btn.setEnabled(True)
            self.get_key_btn.setText("打开下载页")
            self.status_label.setText(
                f"已选择：{preset['name']}（免API Key，可直接添加测试）。{task_hint}"
            )
        else:
            self.apikey_input.setPlaceholderText("请输入API Key")
            self.apikey_input.setFocus()
            self.get_key_btn.setEnabled(bool(url))
            self.get_key_btn.setText("获取免费API Key")
            self.status_label.setText(
                f"已选择：{preset['name']}。需免费注册获取API Key后填入。{task_hint}"
            )

    def _open_register_url(self) -> None:
        index = self.preset_combo.currentIndex()
        if index <= 0:
            return
        preset = self.preset_combo.itemData(index)
        if not preset:
            return
        url = preset.get("register_url", "")
        if not url:
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("AI模型源配置")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        self._config_toggle_btn = QPushButton("▶ 添加/配置AI源（点击展开）")
        self._config_toggle_btn.setStyleSheet(
            "text-align: left; padding: 4px 8px; font-weight: bold;"
        )
        self._config_toggle_btn.clicked.connect(self._toggle_config_section)
        layout.addWidget(self._config_toggle_btn)

        self._config_container = QWidget()
        config_layout = QVBoxLayout(self._config_container)
        config_layout.setContentsMargins(0, 0, 0, 0)

        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("预设模型："))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("-- 选择预设模型自动填充 --", None)
        for p in PRESET_MODELS:
            tag_str = "/".join(p["tags"])
            self.preset_combo.addItem(f"{p['name']} ({tag_str})", p)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_layout.addWidget(self.preset_combo, 1)
        self.get_key_btn = QPushButton("获取免费API Key")
        apply_theme_variant(self.get_key_btn, "warning")
        self.get_key_btn.clicked.connect(self._open_register_url)
        self.get_key_btn.setEnabled(False)
        preset_layout.addWidget(self.get_key_btn)
        config_layout.addLayout(preset_layout)

        self.preset_desc_label = QLabel("")
        self.preset_desc_label.setProperty("role", "secondary")
        self.preset_desc_label.setStyleSheet("padding: 4px 8px; font-size: 12px;")
        self.preset_desc_label.setWordWrap(True)
        config_layout.addWidget(self.preset_desc_label)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("AI源名称")
        self.name_input.setToolTip("名称：此AI源的自定义名称，用于在列表中识别和区分不同的AI模型源。")
        form.addRow("名称：", self.name_input)

        self.type_combo = QComboBox()
        self.type_combo.addItem("在线OpenAI兼容", "online_openai_compatible")
        self.type_combo.addItem("本地Ollama", "local_ollama")
        self.type_combo.setToolTip("类型：选择AI模型的接入方式。在线OpenAI兼容适用于云端API服务；本地Ollama适用于本机运行的Ollama服务。")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("类型：", self.type_combo)

        self.endpoint_input = QLineEdit()
        self.endpoint_input.setPlaceholderText("http://localhost:11434/v1")
        self.endpoint_input.setToolTip("API地址：AI模型服务的接口地址。在线服务填API URL（如https://api.deepseek.com/v1），本地Ollama填http://localhost:11434/v1。")
        form.addRow("API地址：", self.endpoint_input)

        self.model_stack = QStackedWidget()
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("模型名称")
        self.model_input.setToolTip("模型：AI模型的具体名称，如deepseek-chat、qwen-turbo等，须与API服务支持的模型名一致。")
        self.model_stack.addWidget(self.model_input)

        ollama_model_widget = QWidget()
        ollama_model_layout = QHBoxLayout(ollama_model_widget)
        ollama_model_layout.setContentsMargins(0, 0, 0, 0)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(False)
        self.model_combo.setToolTip("模型：从Ollama服务已安装的模型列表中选择。如列表为空请先拉取模型。")
        ollama_model_layout.addWidget(self.model_combo, 1)
        self.refresh_models_btn = QPushButton("刷新")
        self.refresh_models_btn.clicked.connect(self._on_refresh_models)
        ollama_model_layout.addWidget(self.refresh_models_btn)
        self.model_stack.addWidget(ollama_model_widget)
        form.addRow("模型：", self.model_stack)

        self.apikey_input = QLineEdit()
        self.apikey_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.apikey_input.setPlaceholderText("API Key（可选）")
        self.apikey_input.setToolTip("API Key：AI模型服务的访问密钥。在线服务通常需要填写（免费注册获取）；本地Ollama无需填写。")
        apikey_widget = QWidget()
        apikey_layout = QHBoxLayout(apikey_widget)
        apikey_layout.setContentsMargins(0, 0, 0, 0)
        apikey_layout.addWidget(self.apikey_input, 1)
        self.apikey_toggle_btn = QPushButton("显示")
        self.apikey_toggle_btn.setFixedWidth(60)
        self.apikey_toggle_btn.clicked.connect(self._toggle_apikey_visibility)
        apikey_layout.addWidget(self.apikey_toggle_btn)
        form.addRow("API Key：", apikey_widget)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 100)
        self.priority_spin.setToolTip(
            "优先级：数字越小优先级越高。\n"
            "选源分两步：①先按「适用任务」筛出本任务可用的源；②再在筛选结果内按优先级从小到大尝试。\n"
            "注意：优先级只在「同一任务的候选集合」内比较。因此专注某任务的源应取小值（1~10），"
            "通用兜底源应取大值（90~99），否则兜底源会把专属源顶掉。"
        )
        form.addRow("优先级：", self.priority_spin)

        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(1, 100)
        self.weight_spin.setValue(1)
        self.weight_spin.setToolTip(
            "权重：仅在「负载均衡」策略下生效，按权重比例把请求分到各AI源。\n"
            "例如源A权重3、源B权重1，则A分到75%请求、B分到25%。\n"
            "在「故障转移 / 手动指定 / 成本优先」策略下，权重不参与决策，无需调整。"
        )
        form.addRow("权重：", self.weight_spin)
        config_layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加AI源")
        apply_theme_variant(self.add_btn, "success")
        self.add_btn.clicked.connect(self._add_source)
        self.edit_btn = QPushButton("编辑选中")
        self.edit_btn.clicked.connect(self._open_edit_dialog)
        self.edit_btn.setEnabled(False)
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test_connection)
        self.delete_btn = QPushButton("删除选中")
        apply_theme_variant(self.delete_btn, "danger")
        self.delete_btn.clicked.connect(self._delete_source)
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self._load_sources)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.test_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.refresh_btn)
        config_layout.addLayout(btn_layout)

        self._config_container.setVisible(False)
        layout.addWidget(self._config_container)

        layout.addWidget(QLabel("AI源列表："))
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["ID", "名称", "类型", "地址", "模型", "优先级", "权重", "状态", "启用", "适用任务"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnHidden(0, True)

        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._open_edit_dialog())
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        export_layout = QHBoxLayout()
        self.export_btn = QPushButton("导出配置")
        self.export_btn.setToolTip("导出全部 AI 源配置（不含 API Key）到 JSON 文件，可在其他电脑导入")
        self.export_btn.clicked.connect(self._export_sources)
        export_layout.addWidget(self.export_btn)
        self.import_btn = QPushButton("导入配置")
        self.import_btn.setToolTip("从 JSON 文件导入 AI 源配置（需重新填写 API Key）")
        self.import_btn.clicked.connect(self._import_sources)
        export_layout.addWidget(self.import_btn)
        export_layout.addStretch()
        layout.addLayout(export_layout)

        policy_layout = QFormLayout()
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("手动指定", "manual")
        self.strategy_combo.addItem("故障转移", "failover")
        self.strategy_combo.addItem("负载均衡", "load_balance")
        self.strategy_combo.addItem("成本优先", "cost_first")
        self.strategy_combo.setToolTip(
            "路由策略：决定「在同一任务的候选源集合内」如何挑选与排序。\n"
            "• 手动指定：只用指定的那一个源（若它不适用当前任务，则该任务无专属源）。\n"
            "• 故障转移：按优先级从小到大依次尝试，失败自动切下一个；最常用、最可控。\n"
            "• 负载均衡：按权重比例随机分配请求，适合多个等价源分摊压力。\n"
            "• 成本优先：优先选免费/本地源，再按优先级排。\n"
            "选源总流程：①按「适用任务」筛选 → ②按所选策略排序/挑选。"
        )
        policy_layout.addRow("路由策略：", self.strategy_combo)
        self.save_policy_btn = QPushButton("保存路由策略")
        self.save_policy_btn.clicked.connect(self._save_policy)
        policy_layout.addRow("", self.save_policy_btn)
        layout.addLayout(policy_layout)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "secondary")
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)


    def _load_sources(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/config/ai_sources")
        worker.result.connect(self._on_sources_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    @staticmethod
    def _health_status_text(status: str) -> str:
        return {
            "unknown": "未知",
            "healthy": "健康",
            "degraded": "降级",
            "circuit_broken": "熔断",
            "unhealthy": "异常",
        }.get(status, status)

    def _on_sources_loaded(self, sources: list) -> None:
        self._sources_cache = sources
        sorted_sources = sorted(sources, key=lambda s: s.get("priority", 99))
        self.table.setRowCount(0)
        for s in sorted_sources:
            row = self.table.rowCount()
            self.table.insertRow(row)
            task_tags = s.get("task_tags") or []
            if task_tags:
                task_text = ",".join(task_tags)
            else:
                task_text = "全部"
            cells = [
                s.get("source_id", ""),
                s.get("name", ""),
                s.get("source_type", ""),
                s.get("api_endpoint", ""),
                s.get("model_name", ""),
                str(s.get("priority", 1)),
                str(s.get("weight", 1)),
                self._health_status_text(s.get("health_status", "")),
                "是" if s.get("enabled") else "否",
                task_text,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)

    def _add_source(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入名称")
            return
        model_name = self._get_current_model_name()
        if not model_name:
            QMessageBox.warning(self, "提示", "请选择或输入模型名称")
            return
        payload = {
            "name": name,
            "source_type": self.type_combo.currentData(),
            "api_endpoint": self.endpoint_input.text().strip(),
            "model_name": model_name,
            "api_key": self.apikey_input.text().strip() or None,
            "priority": self.priority_spin.value(),
            "weight": self.weight_spin.value(),
            # 选中预设时自动带入其推荐的"适用任务"；未选预设则为空(=通用兜底源)。
            # 添加后仍可双击该行进入编辑对话框精细化调整。
            "task_tags": list(self._pending_preset_task_tags),
        }
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/config/ai_sources", json=payload)
        worker.result.connect(lambda _: (self._load_sources(), self.status_label.setText("AI源已添加"), self._notify_runtime_changed()))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _test_connection(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请选择一行")
            return
        source_id = self.table.item(row, 0).text()
        client = get_api_client()
        self.status_label.setText("测试连接中...")
        worker = ApiWorker(client.post, f"/api/config/ai_sources/{source_id}/test")
        worker.result.connect(self._on_test_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_test_done(self, data: dict) -> None:
        success = data.get("success", False)
        msg = data.get("message", "")
        latency = data.get("latency_ms")
        profile = data.get("model_profile")
        source_id = data.get("source_id", "")
        source_name, current_tasks = self._find_source(source_id)

        if success:
            lat_text = f"（{latency} ms）" if latency is not None else ""
            self.status_label.setText(f"连接测试成功{lat_text}，已展示模型特点")
        else:
            self.status_label.setText(f"连接测试失败：{msg}")

        # 弹出模型特点对话框：展示中文特点说明，并支持一键应用推荐"适用任务"
        dialog = ModelProfileDialog(
            source_name=source_name,
            success=success,
            message=msg,
            latency_ms=latency,
            profile=profile,
            current_tasks=current_tasks,
            parent=self,
        )
        dialog.apply_requested.connect(
            lambda tasks: self._apply_task_tags(source_id, tasks)
        )
        dialog.exec()
        # 测试过程会更新健康状态，刷新列表以反映最新状态
        self._load_sources()

    def _find_source(self, source_id: str) -> tuple[str, list[str]]:
        """从缓存中查找源的显示名与当前任务标签."""
        for s in self._sources_cache:
            if s.get("source_id") == source_id:
                return s.get("name", "AI源"), list(s.get("task_tags") or [])
        return "AI源", []

    def _apply_task_tags(self, source_id: str, tasks: list[str]) -> None:
        """把用户在模型特点对话框中确认的任务标签写回该 AI 源."""
        client = get_api_client()
        worker = ApiWorker(
            client.put,
            f"/api/config/ai_sources/{source_id}",
            json={"task_tags": tasks},
        )
        worker.result.connect(self._on_task_tags_applied)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_task_tags_applied(self, _data: dict) -> None:
        self._load_sources()
        self._notify_runtime_changed()
        self.status_label.setText("适用任务已更新")

    def _delete_source(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请选择一行")
            return
        source_id = self.table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认", "确定删除该AI源？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, f"/api/config/ai_sources/{source_id}")
        worker.result.connect(lambda _: (self._load_sources(), self._notify_runtime_changed()))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _load_policy(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/config/routing_policy")
        worker.result.connect(self._on_policy_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_policy_loaded(self, data: dict) -> None:
        strategy = data.get("strategy", "failover")
        idx = self.strategy_combo.findData(strategy)
        if idx >= 0:
            self.strategy_combo.setCurrentIndex(idx)

    def _save_policy(self) -> None:
        payload = {"strategy": self.strategy_combo.currentData()}
        client = get_api_client()
        worker = ApiWorker(client.put, "/api/config/routing_policy", json=payload)
        worker.result.connect(lambda _: (self.status_label.setText("路由策略已保存"), self._notify_runtime_changed()))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_selection_changed(self) -> None:
        has_selection = self.table.currentRow() >= 0
        self.edit_btn.setEnabled(has_selection)

    def _open_edit_dialog(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选择一个AI源")
            return
        source_id = self.table.item(row, 0).text()
        source_data = None
        for s in self._sources_cache:
            if s.get("source_id") == source_id:
                source_data = s
                break
        if not source_data:
            QMessageBox.warning(self, "提示", "未找到该AI源数据，请刷新列表后重试")
            return
        dialog = AiSourceEditDialog(source_data, self)
        dialog.saved.connect(self._on_edit_saved)
        dialog.exec()

    def _on_edit_saved(self, source_id: str) -> None:
        self._load_sources()
        self._notify_runtime_changed()
        self.status_label.setText("AI源已保存，正在测试连接...")
        self._test_connection_for(source_id)

    def _test_connection_for(self, source_id: str) -> None:
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/config/ai_sources/{source_id}/test")
        worker.result.connect(self._on_auto_test_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_auto_test_done(self, data: dict) -> None:
        success = data.get("success", False)
        msg = data.get("message", "")
        if success:
            self.status_label.setText("保存成功，连接测试通过")
        else:
            self.status_label.setText(f"保存成功，但连接测试失败：{msg}")
        self._load_sources()
        self._notify_runtime_changed()

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)

    def _notify_runtime_changed(self) -> None:
        """驱动主窗口状态栏运行时组件即时刷新 AI 源显示.

        模型管理页的任何变更（增/改/删 AI 源、保存路由策略、自动连接测试）
        都会改变路由选择结果，主窗口右下角的“当前 AI 源”展示必须立即跟上，
        否则用户会有最多 5 秒的视觉迟滞（期间定时轮询兜底，但改动密集时体验差）。
        失败路径（worker.error）不影响路由，不调用本方法。
        """
        # 延迟 import：MainWindow 反向引用本页会形成循环依赖
        from src.ui.main_window import MainWindow

        win = self.window()
        runtime = getattr(win, "_runtime_widget", None) if isinstance(win, MainWindow) else None
        if runtime is not None:
            runtime.refresh_ai_source()

    def _export_sources(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        import json

        path, _ = QFileDialog.getSaveFileName(
            self, "导出 AI 源配置", "ai_sources.json", "JSON文件 (*.json)"
        )
        if not path:
            return
        client = get_api_client()
        try:
            data = client.get("/api/config/ai_sources/export")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(
                self, "导出成功",
                f"已导出 {len(data.get('ai_sources', []))} 个 AI 源配置到\n{path}\n\n"
                f"注意：API Key 未导出，导入后须重新填写。"
            )
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_sources(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        import json

        path, _ = QFileDialog.getOpenFileName(
            self, "导入 AI 源配置", "", "JSON文件 (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "读取失败", str(e))
            return
        client = get_api_client()
        try:
            result = client.post("/api/config/ai_sources/import", json=data)
            QMessageBox.information(
                self, "导入完成",
                f"导入 {result.get('imported', 0)} 个，跳过 {result.get('skipped', 0)} 个已存在。\n\n"
                f"注意：导入的源默认禁用且无 API Key，请逐个填写 Key 并启用。"
            )
            self._load_sources()
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
