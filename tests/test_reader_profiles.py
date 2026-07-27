"""Reader profile registry and application onto CaptureConfig."""

from __future__ import annotations

import pytest

from core.config import CaptureConfig, PdfTrim
from core.reader_profiles import (
    ReaderProfile,
    apply_reader_profile,
    get_reader_profile,
    reader_profile_names,
)


def test_builtin_profiles_present() -> None:
    names = reader_profile_names()
    for expected in ("kindle_app", "kindle_cloud", "aladin_app", "aladin_web"):
        assert expected in names


def test_apply_kindle_app_profile() -> None:
    cfg = CaptureConfig(title="t", base_dir="/x")
    changed = apply_reader_profile(cfg, "kindle_app")
    assert cfg.reader_profile == "kindle_app"
    assert cfg.next_key == "right"
    assert cfg.key_delivery == "sendinput"
    assert cfg.reader_focus_clicks == 2
    assert cfg.reader_focus_x_ratio == 0.5
    assert cfg.reader_focus_y_ratio == 0.5
    assert cfg.focus_click_settle_sec == 1.0
    assert cfg.target_window_title == "Kindle"
    assert cfg.fit_on_start is False
    assert cfg.start_focus_clicks == 0
    # The Kindle app top bar sits inside the captured client area.
    assert cfg.pdf_trim.as_dict() == {
        "left": 0.0,
        "right": 0.0,
        "top": 0.032,
        "bottom": 0.0,
        "fill_top": 0.0,
        "fill_bottom": 0.0,
    }
    assert changed


def test_apply_aladin_app_profile() -> None:
    cfg = CaptureConfig(title="t", base_dir="/x", target_window_title="뇌는 어떻게 나를 조종하는가")
    apply_reader_profile(cfg, "aladin_app")
    assert cfg.next_key == "pagedown"
    assert cfg.key_delivery == "sendinput"
    # Aladin window title is the book name — profile must not overwrite it.
    assert cfg.target_window_title == "뇌는 어떻게 나를 조종하는가"
    assert cfg.reader_focus_clicks == 2
    assert cfg.reader_focus_x_ratio == 0.5
    assert cfg.focus_click_settle_sec == 1.0
    assert cfg.start_focus_clicks == 0
    assert cfg.fit_on_start is False
    assert cfg.pdf_trim.top == 0.010
    assert cfg.pdf_trim.fill_top == 0.026
    assert cfg.pdf_trim.bottom == 0.045


def test_apply_kindle_cloud_uses_center_clicks_not_top() -> None:
    """Cloud used to force clicks=0 (top opens Aa). Center clicks follow kindle_app."""
    cfg = CaptureConfig(title="t", base_dir="/x")
    apply_reader_profile(cfg, "kindle_cloud")
    assert cfg.next_key == "right"
    assert cfg.key_delivery == "pyautogui"
    assert cfg.reader_focus_clicks == 2
    assert cfg.reader_focus_x_ratio == 0.5
    assert cfg.reader_focus_y_ratio == 0.5
    assert cfg.focus_click_settle_sec == 1.0


def test_all_profiles_share_proven_capture_loop() -> None:
    """Every built-in profile inherits the Kindle-proven per-page loop knobs."""
    for name in ("kindle_app", "kindle_cloud", "aladin_app", "aladin_web"):
        cfg = CaptureConfig(title="t", base_dir="/x")
        apply_reader_profile(cfg, name)
        assert cfg.capture_mode == "screen_left_third"
        assert cfg.reader_focus_clicks == 2
        assert cfg.reader_focus_x_ratio == 0.5
        assert cfg.reader_focus_y_ratio == 0.5
        assert cfg.focus_click_settle_sec == 1.0
        assert cfg.fit_on_start is False
        assert cfg.hide_cursor_during_capture is True
        assert cfg.window_capture_backend == "screen"


def test_unknown_profile_raises() -> None:
    cfg = CaptureConfig(title="t", base_dir="/x")
    with pytest.raises(ValueError):
        apply_reader_profile(cfg, "does_not_exist")


def test_none_fields_do_not_override() -> None:
    cfg = CaptureConfig(title="t", base_dir="/x", target_window_title="MyReader")
    apply_reader_profile(cfg, "aladin_app")
    assert cfg.target_window_title == "MyReader"


def test_profile_clamps_focus_clicks_and_normalizes_delivery() -> None:
    prof = ReaderProfile(
        name="tmp",
        reader_focus_clicks=99,
        start_focus_clicks=99,
        key_delivery="PyAutoGUI",
    )
    cfg = CaptureConfig(title="t", base_dir="/x")
    prof.apply_to(cfg)
    assert cfg.reader_focus_clicks == 5
    assert cfg.start_focus_clicks == 5
    assert cfg.key_delivery == "pyautogui"


def test_profile_applies_pdf_trim() -> None:
    prof = ReaderProfile(
        name="tmp",
        pdf_trim=PdfTrim(left=0.05, right=0.04, top=0.02, bottom=0.03),
    )
    cfg = CaptureConfig(title="t", base_dir="/x")
    prof.apply_to(cfg)
    assert cfg.pdf_trim.left == 0.05
    assert cfg.pdf_trim.bottom == 0.03


def test_reader_profile_roundtrips_in_config_json(tmp_path) -> None:
    cfg = CaptureConfig(
        title="t",
        base_dir="/x",
        reader_profile="kindle_app",
        fit_on_start=True,
        start_focus_clicks=0,
        pdf_trim=PdfTrim(left=0.01, right=0.01, top=0.02, bottom=0.02),
    )
    path = tmp_path / "cfg.json"
    cfg.to_json_file(path)
    loaded = CaptureConfig.from_json_file(path)
    assert loaded.reader_profile == "kindle_app"
    assert loaded.fit_on_start is True
    assert loaded.start_focus_clicks == 0
    assert loaded.pdf_trim.top == 0.02


def test_get_reader_profile_returns_none_for_empty() -> None:
    assert get_reader_profile("") is None
