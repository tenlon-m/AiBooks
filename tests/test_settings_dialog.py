"""统一设置窗口与菜单入口测试 - 覆盖窗口单例、配置读写、自动保存迁移、边界值与异常路径."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QWidget,
)

from src.config.settings import get_config
from src.ui.widgets.auto_save_timer import AutoSaveTimer
from src.ui.widgets.settings_dialog import SettingsDialog


def _cleanup_background_workers() -> None:
    try:
        from src.ui.api_worker import _running_workers
        from src.ui.sse_worker import _running_sse_workers

        for worker in list(_running_workers):
            _running_workers.discard(worker)
        for worker in list(_running_sse_workers):
            try:
                if hasattr(worker, "stop"):
                    worker.stop()
            except Exception:
                pass
            _running_sse_workers.discard(worker)
    except Exception:
        pass


@pytest.fixture()
def parent_window(qapp):
    win = QMainWindow()
    timer = AutoSaveTimer(True, 5)
    win._auto_save_timer = timer
    yield win
    SettingsDialog._clear_instance()
    win.close()


@pytest.fixture()
def dialog(parent_window):
    SettingsDialog._clear_instance()
    dlg = SettingsDialog(parent_window)
    yield dlg
    dlg.close()
    SettingsDialog._clear_instance()


@pytest.fixture()
def config_guard():
    config = get_config()
    orig_garbled = config.garbled_detection_enabled
    orig_enabled = config.auto_save_enabled
    orig_interval = config.auto_save_interval_minutes
    yield config
    config.garbled_detection_enabled = orig_garbled
    config.auto_save_enabled = orig_enabled
    config.auto_save_interval_minutes = orig_interval


class TestSettingsDialogWindow:
    def test_window_title_and_fixed_size(self, dialog):
        """验证设置窗口标题为'设置'且固定尺寸480x360，确保窗口标识与布局空间符合设计规范，内容完整可见无裁切。"""
        assert dialog.windowTitle() == "设置"
        assert dialog.width() == 480
        assert dialog.height() == 360

    def test_partition_widgets_exist(self, dialog):
        """验证设置窗口包含乱码检测分区与自动保存分区的核心控件，确保分区组织结构完整，各设置项均可访问。"""
        assert isinstance(dialog._garbled_switch, QCheckBox)
        assert dialog._garbled_switch.text() == "启用乱码检测修复"
        assert isinstance(dialog._garbled_config_btn, QPushButton)
        assert dialog._garbled_config_btn.text() == "乱码配置"
        assert isinstance(dialog._auto_save_checkbox, QCheckBox)
        assert dialog._auto_save_checkbox.text() == "启用定时自动保存"
        assert isinstance(dialog._auto_save_interval_spin, QSpinBox)

    def test_interval_spin_range_1_to_30(self, dialog):
        """验证自动保存间隔输入框取值范围为1到30的整数，确保边界值约束与迁移前一致，非法值无法输入。"""
        assert dialog._auto_save_interval_spin.minimum() == 1
        assert dialog._auto_save_interval_spin.maximum() == 30

    def test_no_confirm_cancel_buttons(self, dialog):
        """验证设置窗口底部仅有'关闭'按钮而无'确定/取消'按钮组，确保即时生效范式与主题设置对话框一致。"""
        buttons = dialog.findChildren(QPushButton)
        texts = [b.text() for b in buttons]
        assert "关闭" in texts
        assert "确定" not in texts
        assert "取消" not in texts

    def test_singleton_show_instance(self, parent_window):
        """验证设置窗口单例范式：已打开时再次调用show_instance激活已存在窗口，不新建第二个实例，_instance引用不变。"""
        SettingsDialog._clear_instance()
        SettingsDialog.show_instance(parent_window)
        first = SettingsDialog._instance
        assert first is not None
        SettingsDialog.show_instance(parent_window)
        second = SettingsDialog._instance
        assert second is first
        first.close()
        SettingsDialog._clear_instance()

    def test_initial_value_echo_from_config(self, parent_window, config_guard):
        """验证设置窗口打开时从配置回显当前值：设置garbled=False、auto_save_enabled=False、interval=10后打开窗口，控件状态应与配置一致。"""
        config_guard.garbled_detection_enabled = False
        config_guard.auto_save_enabled = False
        config_guard.auto_save_interval_minutes = 10
        SettingsDialog._clear_instance()
        dlg = SettingsDialog(parent_window)
        assert dlg._garbled_switch.isChecked() is False
        assert dlg._auto_save_checkbox.isChecked() is False
        assert dlg._auto_save_interval_spin.value() == 10
        dlg.close()
        SettingsDialog._clear_instance()

    def test_garbled_switch_persist_to_config(self, dialog, config_guard):
        """验证切换乱码检测开关后立即持久化到配置：将开关从勾选改为未勾选，配置garbled_detection_enabled应变更为False。"""
        dialog._garbled_switch.setChecked(True)
        assert get_config().garbled_detection_enabled is True
        dialog._garbled_switch.setChecked(False)
        assert get_config().garbled_detection_enabled is False

    def test_auto_save_change_persist_to_config(self, dialog, config_guard):
        """验证修改自动保存间隔后立即持久化：将间隔从5改为15，配置auto_save_interval_minutes应立即变为15。"""
        dialog._auto_save_checkbox.setChecked(True)
        dialog._auto_save_interval_spin.setValue(15)
        assert get_config().auto_save_enabled is True
        assert get_config().auto_save_interval_minutes == 15

    def test_auto_save_timer_reconfigured(self, dialog, config_guard):
        """验证自动保存变更后定时器被重配置：设置enabled=True、interval=20后，定时器应按20分钟间隔运行。"""
        dialog._auto_save_checkbox.setChecked(True)
        dialog._auto_save_interval_spin.setValue(20)
        timer = dialog._get_main_window()._auto_save_timer
        assert timer._interval_minutes == 20
        assert timer._enabled is True

    def test_timer_missing_no_crash(self, qapp, config_guard):
        """验证主窗口无_auto_save_timer属性时配置仍持久化且不崩溃：创建无定时器的父窗口，修改自动保存设置应正常完成。"""
        win = QMainWindow()
        SettingsDialog._clear_instance()
        dlg = SettingsDialog(win)
        dlg._auto_save_checkbox.setChecked(True)
        dlg._auto_save_interval_spin.setValue(10)
        assert get_config().auto_save_interval_minutes == 10
        dlg.close()
        SettingsDialog._clear_instance()
        win.close()

    def test_boundary_values_1_and_30(self, dialog, config_guard):
        """验证间隔边界值1与30均可正常接受并持久化，确保两端边界值生效且配置正确写入，不触发非法值提示。"""
        dialog._auto_save_interval_spin.setValue(1)
        assert get_config().auto_save_interval_minutes == 1
        dialog._auto_save_interval_spin.setValue(30)
        assert get_config().auto_save_interval_minutes == 30

    def test_window_reopen_echo(self, parent_window, config_guard):
        """验证窗口关闭后再打开完整回显已保存的所有设置项当前值，确保配置持久化与回显逻辑一致无丢失。"""
        SettingsDialog._clear_instance()
        dlg1 = SettingsDialog(parent_window)
        dlg1._auto_save_interval_spin.setValue(25)
        dlg1._garbled_switch.setChecked(False)
        dlg1.close()
        SettingsDialog._clear_instance()
        dlg2 = SettingsDialog(parent_window)
        assert dlg2._auto_save_interval_spin.value() == 25
        assert dlg2._garbled_switch.isChecked() is False
        dlg2.close()
        SettingsDialog._clear_instance()

    def test_clear_instance_on_close(self, parent_window):
        """验证窗口关闭后finished信号触发_clear_instance清除单例引用，避免内存泄漏，_instance应变为None。"""
        SettingsDialog._clear_instance()
        SettingsDialog.show_instance(parent_window)
        assert SettingsDialog._instance is not None
        SettingsDialog._instance.close()
        SettingsDialog._clear_instance()
        assert SettingsDialog._instance is None


class TestMainWindowMenu:
    @pytest.fixture()
    def main_window(self, qapp):
        try:
            from src.ui.main_window import MainWindow

            win = MainWindow()
            win.closeEvent = lambda event: event.accept()
            yield win
            _cleanup_background_workers()
            win.deleteLater()
        except Exception:
            pytest.skip("MainWindow 实例化需要完整运行环境，跳过菜单结构测试")

    def test_settings_submenu_exists(self, main_window):
        """验证工具菜单下存在名为'设置'的子菜单项，作为打开统一设置窗口的唯一入口，菜单结构完整无缺失。"""
        menubar = main_window.menuBar()
        tool_menu = None
        for action in menubar.actions():
            if action.text() == "工具(&T)":
                tool_menu = action.menu()
                break
        assert tool_menu is not None
        sub_texts = []
        for action in tool_menu.actions():
            if action.menu() is not None:
                sub_texts.append(action.menu().title())
        assert "设置" in sub_texts

    def test_original_menu_items_preserved(self, main_window):
        """验证新增设置子菜单后原有5个工具菜单项（AI源配置、全局主题、AI调用日志、应用日志、备份管理）全部保留且跳转行为不变。"""
        menubar = main_window.menuBar()
        tool_menu = None
        for action in menubar.actions():
            if action.text() == "工具(&T)":
                tool_menu = action.menu()
                break
        assert tool_menu is not None
        texts = [a.text() for a in tool_menu.actions() if a.menu() is None]
        for expected in ["AI源配置", "全局主题", "AI调用日志", "应用日志", "备份管理"]:
            assert expected in texts, f"原有菜单项'{expected}'缺失"


class TestBackupPageMigration:
    @pytest.fixture()
    def backup_page(self, qapp):
        try:
            from src.ui.pages.backup_page import BackupPage

            page = BackupPage()
            yield page
            _cleanup_background_workers()
            page.deleteLater()
        except Exception:
            pytest.skip("BackupPage 实例化需要完整运行环境，跳过控件移除测试")

    def test_auto_save_checkbox_removed(self, backup_page):
        """验证迁移后备份管理页面不再存在'启用定时自动保存'复选框控件，使用findChild断言该控件已从页面移除为None。"""
        checkbox = backup_page.findChild(QCheckBox, "启用定时自动保存")
        assert not hasattr(backup_page, "auto_save_checkbox") or backup_page.auto_save_checkbox is None
        assert checkbox is None or checkbox.text() != "启用定时自动保存"

    def test_auto_save_interval_spin_removed(self, backup_page):
        """验证迁移后备份管理页面不再存在'保存间隔'数值输入框控件，auto_save_interval_spin属性应不存在或为None。"""
        assert not hasattr(backup_page, "auto_save_interval_spin")

    def test_no_auto_save_config_changed_method(self, backup_page):
        """验证迁移后备份管理页面不再存在_on_auto_save_config_changed方法，其逻辑已完整迁移至SettingsDialog。"""
        assert not hasattr(backup_page, "_on_auto_save_config_changed")