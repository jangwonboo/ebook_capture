"""Windows key delivery helpers."""

from __future__ import annotations

import sys

import pytest

from core.windows_util import _EXTENDED_VKS, _vk_for_key


def test_vk_for_right_arrow() -> None:
    assert _vk_for_key("right") == 0x27
    assert 0x27 in _EXTENDED_VKS


def _patch_click_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[int, int]], list[float]]:
    """Record focus-click coordinates and the sleeps between them."""
    import pyautogui

    from core import windows_util as wu

    clicks: list[tuple[int, int]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(pyautogui, "click", lambda x, y: clicks.append((x, y)))
    monkeypatch.setattr(wu.time, "sleep", lambda sec: sleeps.append(sec))
    return clicks, sleeps


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_reader_focus_click_coords(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.windows_util import _reader_focus_clicks

    clicks, _ = _patch_click_recorder(monkeypatch)
    x, y = _reader_focus_clicks(100, 200, 400, 800, count=2, gap_sec=0)
    assert (x, y) == (180, 360)
    assert clicks == [(180, 360), (180, 360)]


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_reader_focus_clicks_are_not_a_double_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.windows_util import _reader_focus_clicks, double_click_interval_sec

    clicks, sleeps = _patch_click_recorder(monkeypatch)
    _reader_focus_clicks(0, 0, 400, 800, count=3, gap_sec=0.01)
    assert len(clicks) == 3
    # One gap per click pair, each longer than the system double-click time.
    assert len(sleeps) == 2
    assert all(gap > double_click_interval_sec() for gap in sleeps)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_already_foreground_window_is_not_reactivated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Alt tap toggles menu mode and eats the next arrow key — never tap it
    for a window that is already in the foreground."""
    from core import windows_util as wu

    hwnd = 0x1234
    calls: list[str] = []

    class FakeUser32:
        def GetForegroundWindow(self) -> int:
            return hwnd

        def IsIconic(self, _h: int) -> int:
            return 0

        def ShowWindow(self, _h: int, _cmd: int) -> int:
            calls.append("show")
            return 1

        def BringWindowToTop(self, _h: int) -> int:
            calls.append("bring")
            return 1

        def SetForegroundWindow(self, _h: int) -> int:
            calls.append("setforeground")
            return 1

    monkeypatch.setattr(wu, "_win32_modules", lambda: (FakeUser32(), object()))
    monkeypatch.setattr(
        wu, "_unlock_foreground_for_automation", lambda: calls.append("alt_tap")
    )

    assert wu.force_foreground_hwnd(hwnd) is True
    assert calls == []


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_keydown_lparam_marks_extended() -> None:
    from core.windows_util import _keydown_lparam

    lp = _keydown_lparam(0x27)
    assert lp & (1 << 24)


def test_deliver_vk_respects_delivery_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import windows_util as wu

    calls: list[str] = []

    monkeypatch.setattr(wu, "_keyboard_target_hwnd", lambda hwnd: hwnd)
    monkeypatch.setattr(
        wu,
        "_send_vk_attached",
        lambda hwnd, vk: (calls.append("sendinput") or True, "focus=kept@0x1"),
    )
    monkeypatch.setattr(
        wu,
        "_postmessage_vk",
        lambda hwnd, vk: calls.append(f"postmessage:{hwnd}") or True,
    )

    ok, detail = wu._deliver_vk_to_window(0x100, 0x22, "pagedown", delivery="sendinput")
    assert ok is True
    assert calls == ["sendinput"]
    assert "SendInput" in detail

    calls.clear()
    ok, detail = wu._deliver_vk_to_window(
        0x100, 0x22, "pagedown", delivery="postmessage_top"
    )
    assert ok is True
    assert calls == ["postmessage:256"]
    assert "PostMessage top" in detail
