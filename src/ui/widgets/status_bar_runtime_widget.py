"""状态栏运行时信息组件 - 显示当前AI源/运行时长/日期时间."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from src.ai.source_notifier import register_source_hook, unregister_source_hook
from src.ui.api_client import get_api_client
from src.ui.api_worker import ApiWorker

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class StatusBarRuntimeWidget(QWidget):
    """状态栏右下角永久组件，显示三项运行时信息."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._start_timestamp = datetime.now()
        self._workers: list[ApiWorker] = []
        self._tick_count = 0
        self._init_ui()
        self._init_timer()
        self._source_hook = self._on_source_call
        register_source_hook(self._source_hook)

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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(12)

        self.ai_source_label = QLabel("AI源: 加载中...")
        self.ai_source_label.setStyleSheet("color: #555; padding: 0 4px;")
        layout.addWidget(self.ai_source_label)

        self.runtime_label = QLabel("运行: 00:00:00")
        self.runtime_label.setStyleSheet("color: #555; padding: 0 4px;")
        layout.addWidget(self.runtime_label)

        self.datetime_label = QLabel("")
        self.datetime_label.setStyleSheet("color: #555; padding: 0 4px;")
        layout.addWidget(self.datetime_label)

    def _init_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)
        self._on_tick()

    def _on_tick(self) -> None:
        self._tick_count += 1
        self._update_runtime()
        self._update_datetime()
        if self._tick_count % 5 == 0:
            self._fetch_active_ai_source()

    def _on_source_call(
        self,
        source_name: str,
        failover_from: str | None,
        module: str,
        scene: str,
    ) -> None:
        if failover_from:
            text = f"AI源: {source_name} (转移自{failover_from})"
        else:
            text = f"AI源: {source_name}"
        QTimer.singleShot(0, lambda t=text: self.ai_source_label.setText(t))

    def _update_runtime(self) -> None:
        now = datetime.now()
        elapsed = now - self._start_timestamp
        total_seconds = int(elapsed.total_seconds())
        if total_seconds < 0:
            self._start_timestamp = now
            total_seconds = 0
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        self.runtime_label.setText(f"运行: {hours:02d}:{minutes:02d}:{seconds:02d}")

    def _update_datetime(self) -> None:
        now = datetime.now()
        weekday = _WEEKDAYS[now.weekday()]
        self.datetime_label.setText(f"{now.strftime('%Y-%m-%d')} {weekday} {now.strftime('%H:%M:%S')}")

    def _fetch_active_ai_source(self) -> None:
        client = get_api_client()
        worker = ApiWorker(client.get, "/api/config/ai_source/active")
        worker.result.connect(self._on_ai_source_loaded)
        worker.error.connect(self._on_ai_source_error)
        self._add_worker(worker)
        worker.start()

    def _on_ai_source_loaded(self, data: dict) -> None:
        display_text = data.get("display_text", "未知")
        self.ai_source_label.setText(f"AI源: {display_text}")

    def _on_ai_source_error(self, msg: str) -> None:
        self.ai_source_label.setText("AI源: 未知")

    def refresh_ai_source(self) -> None:
        """事件驱动即时刷新AI源显示."""
        self._fetch_active_ai_source()

    def cleanup(self) -> None:
        self._timer.stop()
        unregister_source_hook(self._source_hook)