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
    monkeypatch.setattr(
        pipeline,
        "_capture_one_page",
        lambda c, page, idx, n, p: order.append("capture") or object(),
    )
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
