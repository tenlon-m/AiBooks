"""备份管理页 - 策略配置/手动触发/列表/恢复/删除 + 项目导出导入."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.config.settings import get_config
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker
from src.ui.project_context import get_project_context
from src.ui.theme.theme_qss_builder import apply_theme_variant


class BackupPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ApiWorker] = []
        self._init_ui()
        self._load_policy()
        self._load_backups()
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
        self.table.setRowCount(0)
        self.status_label.clear()

    def has_unsaved_changes(self) -> bool:
        return False

    def _on_cron_preset_changed(self, index: int) -> None:
        self.cron_custom_input.setVisible(index == len(self._cron_presets) - 1)

    def _get_cron_value(self) -> str:
        idx = self.cron_combo.currentIndex()
        if idx == len(self._cron_presets) - 1:
            return self.cron_custom_input.text().strip() or "0 0 * * *"
        return self._cron_presets[idx][1]

    def _set_cron_value(self, cron: str) -> None:
        for i, (_, preset_cron) in enumerate(self._cron_presets):
            if preset_cron == cron:
                self.cron_combo.setCurrentIndex(i)
                return
        self.cron_combo.setCurrentIndex(len(self._cron_presets) - 1)
        self.cron_custom_input.setText(cron)

    def _on_project_changed(self, project_id: str, info: dict) -> None:
        self._load_backups()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("备份与迁移管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 8px;")
        layout.addWidget(title)

        policy_group = QFormLayout()
        self.target_dir_input = QLineEdit()
        self.target_dir_input.setPlaceholderText("备份目标目录")
        self.target_dir_input.setText(str(get_config().backup_dir))
        policy_group.addRow("备份目录：", self.target_dir_input)

        self.cron_combo = QComboBox()
        self._cron_presets = [
            ("每天午夜 00:00", "0 0 * * *"),
            ("每天 06:00", "0 6 * * *"),
            ("每天 12:00", "0 12 * * *"),
            ("每天 18:00", "0 18 * * *"),
            ("每 6 小时", "0 */6 * * *"),
            ("每 12 小时", "0 */12 * * *"),
            ("每周一 00:00", "0 0 * * 1"),
            ("每月 1 日 00:00", "0 0 1 * *"),
            ("自定义...", ""),
        ]
        for label, cron in self._cron_presets:
            self.cron_combo.addItem(label, cron)
        self.cron_combo.currentIndexChanged.connect(self._on_cron_preset_changed)
        self.cron_combo.setToolTip(
            "选择定时备份的执行频率。\n"
            "自定义格式：分 时 日 月 周（5 个字段，空格分隔）\n"
            "例如：0 0 * * * = 每天午夜，30 8 * * * = 每天 8:30"
        )
        self.cron_custom_input = QLineEdit()
        self.cron_custom_input.setPlaceholderText("分 时 日 月 周（如 0 0 * * *）")
        self.cron_custom_input.setVisible(False)
        cron_widget = QWidget()
        cron_layout = QHBoxLayout(cron_widget)
        cron_layout.setContentsMargins(0, 0, 0, 0)
        cron_layout.addWidget(self.cron_combo, 1)
        cron_layout.addWidget(self.cron_custom_input, 1)
        policy_group.addRow("定时备份：", cron_widget)

        self.retain_spin = QSpinBox()
        self.retain_spin.setRange(1, 100)
        self.retain_spin.setValue(10)
        policy_group.addRow("保留份数：", self.retain_spin)

        self.exit_check = QCheckBox("退出时触发")
        self.exit_check.setChecked(True)
        policy_group.addRow("", self.exit_check)

        self.risky_check = QCheckBox("危险操作前触发")
        self.risky_check.setChecked(True)
        policy_group.addRow("", self.risky_check)
        layout.addLayout(policy_group)

        policy_btn_layout = QHBoxLayout()
        self.save_policy_btn = QPushButton("保存备份策略")
        apply_theme_variant(self.save_policy_btn, "info")
        self.save_policy_btn.clicked.connect(self._save_policy)
        self.trigger_btn = QPushButton("立即备份")
        apply_theme_variant(self.trigger_btn, "success")
        self.trigger_btn.clicked.connect(self._trigger_backup)
        policy_btn_layout.addWidget(self.save_policy_btn)
        policy_btn_layout.addWidget(self.trigger_btn)
        layout.addLayout(policy_btn_layout)


        layout.addWidget(QLabel("备份记录："))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["备份ID", "文件路径", "大小(bytes)", "触发者", "创建时间"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        backup_btn_layout = QHBoxLayout()
        self.restore_btn = QPushButton("恢复选中备份")
        self.restore_btn.clicked.connect(self._restore_backup)
        self.delete_btn = QPushButton("删除选中备份")
        apply_theme_variant(self.delete_btn, "danger")
        self.delete_btn.clicked.connect(self._delete_backup)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._load_backups)
        backup_btn_layout.addWidget(self.restore_btn)
        backup_btn_layout.addWidget(self.delete_btn)
        backup_btn_layout.addWidget(self.refresh_btn)
        layout.addLayout(backup_btn_layout)

        layout.addWidget(QLabel("项目导出/导入："))
        export_layout = QHBoxLayout()
        self.export_btn = QPushButton("导出当前项目")
        self.export_btn.clicked.connect(self._export_project)
        self.import_btn = QPushButton("导入项目")
        self.import_btn.clicked.connect(self._import_project)
        export_layout.addWidget(self.export_btn)
        export_layout.addWidget(self.import_btn)
        layout.addLayout(export_layout)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "secondary")
        self.status_label.setStyleSheet("padding: 4px;")
        layout.addWidget(self.status_label)


    def _load_policy(self) -> None:
        """加载后端当前备份策略并回填表单.

        若不做回填，表单会停留在代码里的默认值，用户点「保存」就会把服务端配置覆盖掉。
        """
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/backup/policy")
        worker.result.connect(self._on_policy_loaded)
        worker.error.connect(self._on_policy_load_error)
        self._add_worker(worker)
        worker.start()

    def _on_policy_loaded(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.target_dir_input.setText(data.get("target_dir") or str(get_config().backup_dir))
        self._set_cron_value(data.get("schedule_cron") or "0 0 * * *")
        retain = data.get("retain_count")
        if isinstance(retain, int) and retain > 0:
            self.retain_spin.setValue(min(retain, self.retain_spin.maximum()))
        self.exit_check.setChecked(bool(data.get("trigger_on_exit", True)))
        self.risky_check.setChecked(bool(data.get("trigger_before_risky_op", True)))
        enabled = data.get("enabled", True)
        self.status_label.setText(
            "已加载当前备份策略"
            + ("" if enabled else "（注意：当前策略为「已禁用」状态）")
        )

    def _on_policy_load_error(self, msg: str) -> None:
        # 读取失败不阻塞页面：保持默认值，但明确提示用户保存前先确认
        self.status_label.setText(f"读取备份策略失败：{msg}（表单为默认值，保存将覆盖服务端配置）")

    def _save_policy(self) -> None:
        payload = {
            "enabled": True,
            "schedule_cron": self._get_cron_value(),
            "target_dir": self.target_dir_input.text().strip(),
            "retain_count": self.retain_spin.value(),
            "trigger_on_exit": self.exit_check.isChecked(),
            "trigger_before_risky_op": self.risky_check.isChecked(),
        }
        client = get_api_client()
        worker = ApiWorker(client.put, "/api/backup/policy", json=payload)
        worker.result.connect(lambda _: self.status_label.setText("备份策略已保存"))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _trigger_backup(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/backup/trigger", json={})
        worker.result.connect(lambda _: (self.status_label.setText("备份已触发"), self._load_backups()))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _load_backups(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/backup/list")
        worker.result.connect(self._on_backups_loaded)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_backups_loaded(self, backups: list) -> None:
        self.table.setRowCount(0)
        for b in backups:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(b.get("backup_id", "")))
            self.table.setItem(row, 1, QTableWidgetItem(b.get("file_path", "")))
            self.table.setItem(row, 2, QTableWidgetItem(str(b.get("file_size_bytes", 0))))
            self.table.setItem(row, 3, QTableWidgetItem(b.get("triggered_by", "")))
            self.table.setItem(row, 4, QTableWidgetItem(str(b.get("created_at", ""))))

    def _restore_backup(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请选择一行")
            return
        backup_id = self.table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认", "确定恢复该备份？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/backup/{backup_id}/restore")
        worker.result.connect(lambda _: QMessageBox.information(self, "成功", "备份已恢复"))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _delete_backup(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请选择一行")
            return
        backup_id = self.table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认", "确定删除该备份？")
        if reply != QMessageBox.StandardButton.Yes:
            return
        client = get_api_client()
        worker = ApiWorker(client.delete, f"/api/backup/{backup_id}")
        worker.result.connect(lambda _: self._load_backups())
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _export_project(self) -> None:
        ctx = get_project_context()
        if not ctx.has_project():
            QMessageBox.warning(self, "提示", "请先选择项目")
            return
        target_path, _ = QFileDialog.getSaveFileName(self, "导出项目", "", "AiBooks备份 (*.aibk)")
        if not target_path:
            return
        payload = {"target_path": target_path, "include_ai_call_logs": False, "include_style_libraries": True}
        client = get_api_client()
        worker = ApiWorker(client.post, f"/api/projects/{ctx.project_id}/export", json=payload)
        worker.result.connect(lambda d: QMessageBox.information(self, "成功", f"项目已导出：{d}"))
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _import_project(self) -> None:
        source_path, _ = QFileDialog.getOpenFileName(self, "导入项目", "", "AiBooks备份 (*.aibk)")
        if not source_path:
            return
        payload = {"source_path": source_path, "conflict_strategy": "rename"}
        client = get_api_client()
        worker = ApiWorker(client.post, "/api/projects/import", json=payload)
        worker.result.connect(self._on_import_done)
        worker.error.connect(self._on_error)
        self._add_worker(worker)
        worker.start()

    def _on_import_done(self, data: dict) -> None:
        QMessageBox.information(
            self, "导入成功",
            f"项目已导入：{data}\n\n请确认 AI 源配置可用后再开始撰写。\n（新电脑的 AI 源配置可与原电脑不同）"
        )
        self.status_label.setText("项目导入成功，请确认AI源配置")

    def _on_error(self, msg: str) -> None:
        self.status_label.setText(f"错误：{msg}")
        QMessageBox.critical(self, "错误", msg)
