"""Anthropic Claude Vision OCR for captured ebook page images."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

from core.google_ocr import _extract_json_object, _load_env, _ssl_context, resolve_ocr_prompt, sanitize_page_structure


DEFAULT_ANTHROPIC_OCR_MODEL = "claude-haiku-4-5-20251001"


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/png")


def _client():
    _load_env()
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY is not set (environment or .env)")
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic is required for Anthropic OCR.") from exc

    try:
        http_client = anthropic.DefaultHttpxClient(verify=_ssl_context())
    except Exception:
        http_client = None
    return anthropic.Anthropic(http_client=http_client, max_retries=5, timeout=300.0)


def _call_anthropic_json(
    image_path: Path,
    prompt: str,
    *,
    model: str = DEFAULT_ANTHROPIC_OCR_MODEL,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> dict[str, Any]:
    path = Path(image_path)
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    json_prompt = (
        f"{prompt}\n\n"
        "JSON encoding requirement: encode every text value as strict JSON. "
        "Use JSON escaping for embedded double quotes and line breaks inside string values. "
        "Do not emit raw line breaks inside JSON strings."
    )
    client = _client()
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": _mime_type(path),
                                    "data": data,
                                },
                            },
                            {"type": "text", "text": json_prompt},
                        ],
                    }
                ],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("Anthropic OCR refused this page")
            text = "".join(block.text for block in response.content if block.type == "text")
            return _extract_json_object(text)
        except (json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
        except Exception as exc:  # noqa: BLE001 - API exposes many exception types
            last_error = exc
        message = str(last_error).lower()
        retryable = isinstance(last_error, json.JSONDecodeError) or any(
            token in message for token in ("429", "rate", "overload", "temporar", "timeout", "json")
        )
        if retryable and attempt < max_retries - 1:
            time.sleep(base_delay * (2**attempt))
            continue
        break
    raise RuntimeError(f"Anthropic OCR API call failed: {last_error}") from last_error


def extract_page_structure_from_image(
    image_path: Path | str,
    *,
    page_num: int = 1,
    lang_hint: str = "kor",
    prompt: str = "",
    prompt_file: str = "",
    model: str = DEFAULT_ANTHROPIC_OCR_MODEL,
) -> dict[str, Any]:
    """Extract structured OCR JSON from one PNG/JPEG ebook page."""
    resolved_prompt = resolve_ocr_prompt(
        lang_hint=lang_hint,
        page_num=page_num,
        custom_prompt=prompt,
        prompt_file=prompt_file,
    )
    raw = _call_anthropic_json(Path(image_path), resolved_prompt, model=model)
    result = sanitize_page_structure(raw, page_num)
    if not result["text"] and not result["sections"]:
        raw = _call_anthropic_json(Path(image_path), resolved_prompt, model=model)
        result = sanitize_page_structure(raw, page_num)
    return result
