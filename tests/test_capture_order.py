"""Capture phase step order (reader focus clicks happen before each screenshot)."""

from __future__ import annotations

from typing import Any

import pytest

from core import pipeline
from core.config import CaptureConfig


def test_focus_clicks_run_before_each_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cfg = CaptureConfig(title="t", base_dir=str(tmp_path), n_pages=3)
    order: list[str] = []

    monkeypatch.setattr(pipeline, "_pin_capture_target", lambda c, p: None)
    monkeypatch.setattr(pipeline, "_can_skip_page", lambda *a, **k: False)
    monkeypatch.setattr(
        pipeline, "_focus_reader_before_capture", lambda c, p: order.append("focus")
    )
    def _fake_capture(c, page, idx, n, p):
        order.append("capture")
        # stop_repeat dedup hashes shot.tobytes(); give each page unique bytes so
        # no false "end of book" early-stop while exercising the step order.
        return type("_Shot", (), {"tobytes": lambda self, _n=len(order): bytes([_n])})()

    monkeypatch.setattr(pipeline, "_capture_one_page", _fake_capture)
    monkeypatch.setattr(pipeline, "_save_image_atomic", lambda shot, path: None)
    monkeypatch.setattr(
        pipeline, "_mark_page", lambda *a, **k: None
    )
    monkeypatch.setattr(
        pipeline, "_send_page_turn_key", lambda c, p: order.append("key")
    )
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)

    state: dict[str, Any] = {}
    pipeline._run_phase_capture(cfg, state, 3, None)

    assert order == [
        "focus",
        "capture",
        "key",
        "focus",
        "capture",
        "key",
        "focus",
        "capture",
    ]


def test_focus_clicks_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = CaptureConfig(title="t", base_dir="/x", reader_focus_clicks=0)
    calls: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "_screen_region",
        lambda c: calls.append("region") or (0, 0, 100, 100),
    )
    pipeline._focus_reader_before_capture(cfg, None)
    assert calls == []


def _shot(data: bytes):
    return type("_Shot", (), {"tobytes": lambda self, _b=data: _b})()


def test_page_turn_retry_resends_key_when_frame_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Focus lost -> key dropped -> same frame. Retry must re-focus, resend,
    re-shoot and NOT trigger end-of-book."""
    cfg = CaptureConfig(
        title="t",
        base_dir=str(tmp_path),
        n_pages=3,
        page_turn_retries=2,
        stop_repeat_pages=2,
    )
    order: list[str] = []
    # Frames: p1=A, p2 first shot=A (key dropped), after retry=B, p3=C.
    frames = iter([b"A", b"A", b"B", b"C"])

    monkeypatch.setattr(pipeline, "_pin_capture_target", lambda c, p: None)
    monkeypatch.setattr(pipeline, "_can_skip_page", lambda *a, **k: False)
    monkeypatch.setattr(
        pipeline, "_focus_reader_before_capture", lambda c, p: order.append("focus")
    )
    monkeypatch.setattr(
        pipeline,
        "_capture_one_page",
        lambda c, page, idx, n, p: order.append("capture") or _shot(next(frames)),
    )
    monkeypatch.setattr(pipeline, "_save_image_atomic", lambda shot, path: None)
    monkeypatch.setattr(pipeline, "_mark_page", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_send_page_turn_key", lambda c, p: order.append("key"))
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)

    n = pipeline._run_phase_capture(cfg, {}, 3, None)
    assert n == 3
    assert order == [
        "focus", "capture", "key",  # page 1
        "focus", "capture",  # page 2: unchanged frame
        "focus", "key", "focus", "capture",  # retry 1 -> moved
        "key",
        "focus", "capture",  # page 3
    ]


def test_page_turn_retry_exhausted_still_counts_as_repeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cfg = CaptureConfig(
        title="t",
        base_dir=str(tmp_path),
        n_pages=4,
        page_turn_retries=1,
        stop_repeat_pages=1,
    )
    keys: list[int] = []
    monkeypatch.setattr(pipeline, "_pin_capture_target", lambda c, p: None)
    monkeypatch.setattr(pipeline, "_can_skip_page", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "_focus_reader_before_capture", lambda c, p: None)
    monkeypatch.setattr(
        pipeline, "_capture_one_page", lambda c, page, idx, n, p: _shot(b"SAME")
    )
    monkeypatch.setattr(pipeline, "_save_image_atomic", lambda shot, path: None)
    monkeypatch.setattr(pipeline, "_mark_page", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_unmark_page", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_send_page_turn_key", lambda c, p: keys.append(1))
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)

    n = pipeline._run_phase_capture(cfg, {}, 4, None)
    # Page 1 real; page 2 identical even after one retry -> book ended at page 1.
    assert n == 1
    assert len(keys) == 2  # initial key + one retry


def test_screenshot_until_stable_waits_for_identical_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = CaptureConfig(
        title="t", base_dir="/x", settle_stable_sec=0.1, settle_max_sec=5.0
    )
    frames = iter([b"toolbar", b"fading", b"page", b"page"])
    monkeypatch.setattr(pipeline, "screenshot_region", lambda *a: _shot(next(frames)))
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)
    log: list[str] = []
    out = pipeline._screenshot_until_stable(cfg, 0, 0, 10, 10, log.append)
    assert out.tobytes() == b"page"
    assert any(m.startswith("SETTLE_STABLE") for m in log)


def test_screenshot_until_stable_gives_up_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = CaptureConfig(
        title="t", base_dir="/x", settle_stable_sec=0.1, settle_max_sec=0.25
    )
    counter = iter(range(1000))
    monkeypatch.setattr(
        pipeline, "screenshot_region", lambda *a: _shot(bytes([next(counter)]))
    )
    clock = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    monkeypatch.setattr(pipeline.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)
    log: list[str] = []
    pipeline._screenshot_until_stable(cfg, 0, 0, 10, 10, log.append)
    assert any(m.startswith("SETTLE_TIMEOUT") for m in log)


def test_screenshot_until_stable_disabled_takes_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = CaptureConfig(title="t", base_dir="/x", settle_stable_sec=0.0)
    calls: list[int] = []
    monkeypatch.setattr(
        pipeline, "screenshot_region", lambda *a: calls.append(1) or object()
    )
    pipeline._screenshot_until_stable(cfg, 0, 0, 10, 10, None)
    assert calls == [1]


def test_keep_pointer_outside_never_moves_pointer_inside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = CaptureConfig(
        title="t",
        base_dir="/x",
        capture_mode="manual",
        keep_pointer_outside=True,
        hide_cursor_during_capture=True,
    )
    moves: list[tuple] = []
    monkeypatch.setattr(pipeline, "_screen_region", lambda c: (0, 0, 100, 100))
    monkeypatch.setattr(pipeline.pyautogui, "position", lambda: (500, 500))
    monkeypatch.setattr(pipeline.pyautogui, "moveTo", lambda *a, **k: moves.append(a))
    monkeypatch.setattr(pipeline, "screenshot_region", lambda *a: object())
    pipeline._capture_one_page(cfg, 1, 0, 1, None)
    assert moves == []


def test_same_page_tolerates_reader_overlay_but_not_a_page_turn() -> None:
    """A hover arrow changes a handful of pixels (meandiff ~0.003); a real page
    turn between similar text pages moves the mean by ~4. The default tolerance
    must sit between the two."""
    from PIL import Image, ImageDraw

    cfg = CaptureConfig(title="t", base_dir="/x")  # stop_repeat_tolerance=0.3
    page = Image.new("RGB", (640, 800), (255, 255, 255))
    d = ImageDraw.Draw(page)
    for y in range(100, 700, 20):
        d.rectangle([80, y, 560, y + 6], fill=(0, 0, 0))
    overlay = page.copy()
    ImageDraw.Draw(overlay).polygon([(620, 400), (632, 410), (620, 420)], fill=(90, 90, 90))
    other = Image.new("RGB", (640, 800), (255, 255, 255))
    d2 = ImageDraw.Draw(other)
    for y in range(110, 700, 20):
        d2.rectangle([80, y, 560, y + 6], fill=(0, 0, 0))

    fp_page = pipeline._page_fingerprint(page)
    same, diff = pipeline._same_page(cfg, fp_page, pipeline._page_fingerprint(overlay))
    assert same and diff < 0.3
    same, diff = pipeline._same_page(cfg, fp_page, pipeline._page_fingerprint(other))
    assert not same and diff > 0.3
    # Exact mode: the overlay is a different frame.
    cfg.stop_repeat_tolerance = 0.0
    same, _ = pipeline._same_page(cfg, fp_page, pipeline._page_fingerprint(overlay))
    assert not same
    # No previous page: never "same".
    assert pipeline._same_page(cfg, None, fp_page) == (False, float("inf"))


def test_end_of_book_detected_through_overlay_noise(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Last page repeated, once with a hover arrow: still end-of-book."""
    from PIL import Image, ImageDraw

    cfg = CaptureConfig(
        title="t", base_dir=str(tmp_path), n_pages=5, page_turn_retries=0, stop_repeat_pages=2
    )
    first = Image.new("RGB", (320, 400), (255, 255, 255))
    ImageDraw.Draw(first).rectangle([40, 40, 280, 60], fill=(0, 0, 0))
    last = Image.new("RGB", (320, 400), (255, 255, 255))
    ImageDraw.Draw(last).rectangle([40, 300, 280, 320], fill=(0, 0, 0))
    last_arrow = last.copy()
    ImageDraw.Draw(last_arrow).polygon([(310, 200), (316, 205), (310, 210)], fill=(80, 80, 80))
    frames = iter([first, last, last, last_arrow, last])

    monkeypatch.setattr(pipeline, "_pin_capture_target", lambda c, p: None)
    monkeypatch.setattr(pipeline, "_can_skip_page", lambda *a, **k: False)
    monkeypatch.setattr(pipeline, "_focus_reader_before_capture", lambda c, p: None)
    monkeypatch.setattr(pipeline, "_capture_one_page", lambda c, page, idx, n, p: next(frames))
    monkeypatch.setattr(pipeline, "_save_image_atomic", lambda shot, path: None)
    monkeypatch.setattr(pipeline, "_mark_page", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_unmark_page", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_send_page_turn_key", lambda c, p: None)
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)

    # page1=first, page2=last, page3=last (repeat 1), page4=last+arrow (repeat 2) -> stop at 2.
    assert pipeline._run_phase_capture(cfg, {}, 5, None) == 2


def test_keep_display_awake_is_safe_context_manager() -> None:
    from core.windows_util import keep_display_awake

    with keep_display_awake(True) as k:
        assert isinstance(k.active, bool)
    assert k.active is False
    with keep_display_awake(False) as off:
        assert off.active is False
