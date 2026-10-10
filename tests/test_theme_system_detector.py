"""SystemThemeDetector 单元测试."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from src.ui.theme.system_theme_detector import SystemThemeDetector


class TestSystemThemeDetector:
    def test_is_light_mode_returns_bool(self, qapp):
        detector = SystemThemeDetector()
        result = detector.is_light_mode()
        assert isinstance(result, bool)

    def test_start_stop_watching(self, qapp):
        detector = SystemThemeDetector()
        detector.start_watching()
        assert detector._timer is not None
        assert detector._timer.isActive()
        detector.stop_watching()
        assert detector._timer is None

    def test_poll_no_change_no_signal(self, qapp):
        detector = SystemThemeDetector()
        detector.start_watching()
        emitted = []
        detector.system_theme_changed.connect(lambda v: emitted.append(v))
        with patch.object(detector, "is_light_mode", return_value=detector._is_light):
            detector._poll()
        assert len(emitted) == 0
        detector.stop_watching()

    def test_poll_change_emits_signal(self, qapp):
        detector = SystemThemeDetector()
        detector.start_watching()
        original = detector._is_light
        emitted = []
        detector.system_theme_changed.connect(lambda v: emitted.append(v))
        with patch.object(detector, "is_light_mode", return_value=not original):
            detector._poll()
        assert len(emitted) == 1
        assert emitted[0] == (not original)
        detector.stop_watching()