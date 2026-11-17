from __future__ import annotations

from pathlib import Path

from core.anthropic_ocr import _mime_type


def test_mime_type_for_supported_images() -> None:
    assert _mime_type(Path("page.png")) == "image/png"
    assert _mime_type(Path("page.jpg")) == "image/jpeg"
    assert _mime_type(Path("page.webp")) == "image/webp"
