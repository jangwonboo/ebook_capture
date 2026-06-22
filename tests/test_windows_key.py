"""Windows key delivery helpers."""

from __future__ import annotations

import sys

import pytest

from core.windows_util import _EXTENDED_VKS, _vk_for_key


def test_vk_for_right_arrow() -> None:
    assert _vk_for_key("right") == 0x27
    assert 0x27 in _EXTENDED_VKS


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")
def test_reader_focus_click_coords() -> None:
    from core.windows_util import _reader_focus_clicks

    class FakeGui:
        clicks: list[tuple[int, int]] = []

        @staticmethod
        def click(x: int, y: int) -> None:
            FakeGui.clicks.append((x, y))

    import core.windows_util as wu

    wu.time.sleep = lambda _: None  # type: ignore[assignment]
    import pyautogui

    pyautogui.click = FakeGui.click  # type: ignore[assignment]
    FakeGui.clicks.clear()
    x, y = _reader_focus_clicks(100, 200, 400, 800, count=2, gap_sec=0)
    assert (x, y) == (300, 600)
    assert FakeGui.clicks == [(300, 600), (300, 600)]


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
        lambda hwnd, vk: calls.append("sendinput") or True,
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
