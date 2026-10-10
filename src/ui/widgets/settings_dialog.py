"""统一设置窗口 - 聚合乱码检测与自动保存等全局设置项，单例非模态即时生效."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config.settings import get_config
from src.ui.theme.theme_manager import ThemeManager
from src.ui.widgets.garbled_config_dialog import GarbledConfigDialog
from src.utils.logger import get_logger

logger = get_logger()


class SettingsDialog(QDialog):
    """统一设置窗口（单例，非模态，即时生效）."""

    _instance: "SettingsDialog | None" = None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedSize(480, 360)
        self._init_ui()
        self._load_current_state()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        garbled_title = QLabel("乱码检测")
        garbled_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(garbled_title)

        self._garbled_switch = QCheckBox("启用乱码检测修复")
        self._garbled_switch.setToolTip("开启后对 AI 生成/修复/润色/填充/保存结果进行乱码与格式检测修复")
        self._garbled_switch.stateChanged.connect(self._on_garbled_switch_changed)
        layout.addWidget(self._garbled_switch)

        garbled_btn_layout = QHBoxLayout()
        garbled_btn_layout.setContentsMargins(20, 0, 0, 0)
        self._garbled_config_btn = QPushButton("乱码配置")
        self._garbled_config_btn.clicked.connect(self._open_garbled_config)
        garbled_btn_layout.addWidget(self._garbled_config_btn)
        garbled_btn_layout.addStretch()
        layout.addLayout(garbled_btn_layout)

        autosave_title = QLabel("自动保存")
        autosave_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(autosave_title)

        self._auto_save_checkbox = QCheckBox("启用定时自动保存")
        self._auto_save_checkbox.stateChanged.connect(self._on_auto_save_changed)
        layout.addWidget(self._auto_save_checkbox)

        interval_layout = QHBoxLayout()
        interval_layout.setContentsMargins(20, 0, 0, 0)
        interval_layout.addWidget(QLabel("保存间隔(分钟):"))
        self._auto_save_interval_spin = QSpinBox()
        self._auto_save_interval_spin.setRange(1, 30)
        self._auto_save_interval_spin.valueChanged.connect(self._on_auto_save_changed)
        interval_layout.addWidget(self._auto_save_interval_spin)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)

        layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

    def _get_main_window(self) -> QWidget | None:
        parent = self.parent()
        if parent is not None and hasattr(parent, "statusBar"):
            return parent
        return self.window()

    def _load_current_state(self) -> None:
        try:
            config = get_config()
            self._garbled_switch.blockSignals(True)
            self._auto_save_checkbox.blockSignals(True)
            self._auto_save_interval_spin.blockSignals(True)
            self._garbled_switch.setChecked(config.garbled_detection_enabled)
            self._auto_save_checkbox.setChecked(config.auto_save_enabled)
            self._auto_save_interval_spin.setValue(config.auto_save_interval_minutes)
            self._garbled_switch.blockSignals(False)
            self._auto_save_checkbox.blockSignals(False)
            self._auto_save_interval_spin.blockSignals(False)
        except Exception:
            logger.exception("设置窗口加载当前配置失败，回退默认值")
            self._garbled_switch.setChecked(True)
            self._auto_save_checkbox.setChecked(True)
            self._auto_save_interval_spin.setValue(5)
            main_window = self._get_main_window()
            if hasattr(main_window, "statusBar"):
                main_window.statusBar().showMessage("部分设置加载失败，已使用默认值", 3000)

    def _on_garbled_switch_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        try:
            get_config().garbled_detection_enabled = enabled
        except Exception:
            logger.exception("乱码检测开关持久化失败")
        logger.info(f"乱码检测开关变更为: {enabled}")
        main_window = self._get_main_window()
        if hasattr(main_window, "statusBar"):
            main_window.statusBar().showMessage("乱码检测设置已更新", 2000)

    def _open_garbled_config(self) -> None:
        try:
            dialog = GarbledConfigDialog(self)
            dialog.exec()
        except Exception:
            logger.exception("乱码配置对话框打开失败")
            QMessageBox.warning(self, "提示", "乱码配置打开失败，请查看应用日志")

    def _on_auto_save_changed(self) -> None:
        enabled = self._auto_save_checkbox.isChecked()
        interval = self._auto_save_interval_spin.value()
        if interval < 1 or interval > 30:
            QMessageBox.warning(
                self,
                "设置错误",
                "保存间隔须为 1-30 分钟之间的整数",
            )
            return
        config = get_config()
        config.auto_save_enabled = enabled
        config.auto_save_interval_minutes = interval
        self._reconfigure_auto_save_timer(enabled, interval)
        main_window = self._get_main_window()
        if hasattr(main_window, "statusBar"):
            main_window.statusBar().showMessage("自动保存配置已更新", 2000)

    def _reconfigure_auto_save_timer(self, enabled: bool, interval: int) -> None:
        main_window = self._get_main_window()
        if main_window is not None and hasattr(main_window, "_auto_save_timer"):
            main_window._auto_save_timer.reconfigure(enabled, interval)
        else:
            logger.warning("定时器实例不存在，跳过重配置")

    def _on_theme_changed(self, theme_data: dict) -> None:
        pass

    @classmethod
    def show_instance(cls, parent: QWidget) -> None:
        """单例化显示设置窗口."""
        if cls._instance is not None:
            cls._instance.raise_()
            cls._instance.activateWindow()
            return
        try:
            dlg = cls(parent)
            dlg.finished.connect(cls._clear_instance)
            cls._instance = dlg
            dlg.show()
        except Exception:
            logger.exception("设置窗口打开失败")
            main_window = parent
            if hasattr(main_window, "statusBar"):
                main_window.statusBar().showMessage("设置窗口打开失败，请查看应用日志", 3000)

    @classmethod
    def _clear_instance(cls) -> None:
        """清除单例引用."""
        cls._instance = None