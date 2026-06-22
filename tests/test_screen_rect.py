"""Fixed screen capture rect helpers."""

from __future__ import annotations

import sys

import pytest

from core.config import CAPTURE_SCREEN_LEFT_THIRD, is_fixed_screen_capture_mode


def test_is_fixed_screen_capture_mode() -> None:
    assert is_fixed_screen_capture_mode(CAPTURE_SCREEN_LEFT_THIRD)
    assert not is_fixed_screen_capture_mode("window_full")


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_screen_left_third_rect_origin_and_width() -> None:
    from core.windows_util import primary_screen_metrics, screen_left_third_rect

    pl, pt, pw, ph = primary_screen_metrics()
    left, top, width, height = screen_left_third_rect()
    assert (left, top) == (0, 0)
    assert width == max(1, pw // 3)
    assert height == ph


def test_resolve_screen_rect_screen_mode_without_hwnd(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import windows_util as wu

    monkeypatch.setattr(wu, "screen_left_third_rect", lambda: (0, 0, 640, 1080))
    assert wu.resolve_screen_rect("AnyTitle", CAPTURE_SCREEN_LEFT_THIRD) == (0, 0, 640, 1080)


def test_resolve_screen_rect_screen_mode_uses_client_after_hwnd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import windows_util as wu

    monkeypatch.setattr(
        wu,
        "capture_rect_screen_left_third",
        lambda hwnd, use_client_rect=True: (0, 32, 640, 1048),
    )
    assert wu.resolve_screen_rect(
        "AnyTitle",
        CAPTURE_SCREEN_LEFT_THIRD,
        pinned_hwnd=0x100,
    ) == (0, 32, 640, 1048)
