"""Google Gemini OCR helpers (API-key based, same style as doc_metadata)."""

from __future__ import annotations

import os
import json
import re
import ssl
import time
from pathlib import Path
from typing import Any

DEFAULT_GOOGLE_OCR_MODEL = "gemini-2.5-flash"


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("Google OCR layout response did not contain JSON")
        raw = json.loads(cleaned[start : end + 1])
    if not isinstance(raw, dict):
        raise RuntimeError("Google OCR layout response must be a JSON object")
    return raw


def _normalize_bbox(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw.get("x", raw.get("left")))
        y = float(raw.get("y", raw.get("top")))
        w = float(raw.get("w", raw.get("width")))
        h = float(raw.get("h", raw.get("height")))
    except (TypeError, ValueError):
        return None

    # Accept either 0..1 normalized values or percent-like / 1000-scale values.
    max_value = max(abs(x), abs(y), abs(w), abs(h))
    if max_value > 1.0:
        scale = 1000.0 if max_value > 100.0 else 100.0
        x, y, w, h = x / scale, y / scale, w / scale, h / scale

    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0 - x, w))
    h = max(0.0, min(1.0 - y, h))
    if w <= 0.0 or h <= 0.0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _sanitize_layout(raw: dict[str, Any], image_path: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(image_path) as img:
        image_width, image_height = img.size

    blocks: list[dict[str, Any]] = []
    for item in raw.get("blocks", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        bbox = _normalize_bbox(item.get("bbox"))
        if not text or bbox is None:
            continue
        confidence_raw = item.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        blocks.append({"text": text, "bbox": bbox, "confidence": confidence})

    if not blocks:
        text = str(raw.get("text", "")).strip()
        if text:
            blocks.append(
                {
                    "text": text,
                    "bbox": {"x": 0.03, "y": 0.03, "w": 0.94, "h": 0.94},
                    "confidence": 0.0,
                }
            )
    if not blocks:
        raise RuntimeError("Google OCR layout response did not include text blocks")

    return {
        "image_width": int(raw.get("image_width") or image_width),
        "image_height": int(raw.get("image_height") or image_height),
        "text": "\n".join(block["text"] for block in blocks).strip(),
        "blocks": blocks,
    }


def _layout_from_plain_text(text: str, image_path: Path) -> dict[str, Any]:
    """Build a coarse searchable-PDF layout when Gemini returns malformed JSON."""
    from PIL import Image

    with Image.open(image_path) as img:
        image_width, image_height = img.size

    cleaned = (text or "").strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines and cleaned:
        lines = [cleaned]
    if not lines:
        raise RuntimeError("Google OCR fallback did not return text")

    top_margin = 0.04
    usable_height = 0.92
    row_height = usable_height / max(1, len(lines))
    block_height = max(0.003, min(0.08, row_height * 0.85))
    blocks = []
    for index, line in enumerate(lines):
        y = min(0.99 - block_height, top_margin + (index * row_height))
        blocks.append(
            {
                "text": line,
                "bbox": {"x": 0.03, "y": y, "w": 0.94, "h": block_height},
                "confidence": 0.0,
            }
        )

    return {
        "image_width": image_width,
        "image_height": image_height,
        "text": "\n".join(lines),
        "blocks": blocks,
        "layout_fallback": "plain_text",
    }


def _load_env() -> None:
    """Load .env without printing secrets.

    Prefer the current/project .env, and also support the sibling doc_metadata .env
    used by the user's existing Google API workflow.
    """
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - dependency message path
        raise RuntimeError(
            "python-dotenv is required for Google OCR. Install requirements.txt."
        ) from exc

    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path(__file__).resolve().parents[2] / "doc_metadata" / ".env",
    ]
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=True)
    load_dotenv(override=True)


def _ssl_context() -> ssl.SSLContext:
    """Build the SSL context used by google-genai/httpx.

    GOOGLE_API_TRUST_MODE:
    - auto (default): OS trust store when available, otherwise certifi.
    - system: require OS trust store (useful on corporate Windows).
    - certifi: public CA bundle only (useful on open networks).

    GOOGLE_API_CA_BUNDLE / SSL_CERT_FILE can add a corporate/root CA. The extra
    CA may be a PEM bundle or a DER-encoded .cer exported from Windows certmgr.
    """
    mode = os.getenv("GOOGLE_API_TRUST_MODE", "auto").strip().lower()
    extra_ca = os.getenv("GOOGLE_API_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
    capath = os.getenv("SSL_CERT_DIR")

    def certifi_context() -> ssl.SSLContext:
        try:
            import certifi

            base_cafile = certifi.where()
        except ImportError:
            base_cafile = None
        return ssl.create_default_context(cafile=base_cafile, capath=capath)

    def system_context() -> ssl.SSLContext:
        import truststore

        result = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if capath:
            result.load_verify_locations(capath=capath)
        return result

    if mode not in {"auto", "system", "certifi"}:
        raise RuntimeError(
            "GOOGLE_API_TRUST_MODE must be one of: auto, system, certifi"
        )

    try:
        if mode == "certifi":
            ctx = certifi_context()
        elif mode == "system":
            ctx = system_context()
        else:
            try:
                ctx = system_context()
            except ImportError:
                ctx = certifi_context()
    except ImportError as exc:
        raise RuntimeError(
            "truststore is required when GOOGLE_API_TRUST_MODE=system"
        ) from exc
    except ssl.SSLError as exc:
        if mode == "auto":
            ctx = certifi_context()
        else:
            raise RuntimeError(f"Failed to initialize SSL context: {exc}") from exc

    if not extra_ca:
        return ctx

    ca_path = Path(extra_ca).expanduser()
    if not ca_path.is_file():
        if mode == "certifi":
            return ctx
        raise RuntimeError(f"Google OCR CA bundle not found: {ca_path}")

    data = ca_path.read_bytes()
    try:
        if b"-----BEGIN CERTIFICATE-----" in data:
            ctx.load_verify_locations(cafile=str(ca_path))
        else:
            # Windows Export-Certificate often writes DER .cer. Convert it in-memory.
            pem = ssl.DER_cert_to_PEM_cert(data)
            ctx.load_verify_locations(cadata=pem)
    except (ValueError, ssl.SSLError) as exc:
        if mode == "certifi":
            return ctx
        raise RuntimeError(
            "Google OCR CA bundle is not a valid PEM bundle or DER certificate: "
            f"{ca_path}"
        ) from exc
    return ctx


def _client():
    _load_env()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY environment variable not set")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - dependency message path
        raise RuntimeError("google-genai is required for Google OCR.") from exc

    ctx = _ssl_context()
    http_options = types.HttpOptions(
        client_args={"verify": ctx},
        async_client_args={"verify": ctx},
    )
    return genai.Client(api_key=api_key, http_options=http_options)


def extract_text_from_image(
    image_path: Path | str,
    *,
    lang_hint: str = "kor",
    model: str | None = None,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> str:
    """Extract visible text from an image using Gemini."""
    try:
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - dependency message path
        raise RuntimeError("google-genai is required for Google OCR.") from exc

    path = Path(image_path)
    data = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    prompt = (
        "Extract all visible text from this ebook page image. "
        "Return only the OCR text, preserving paragraph order and line breaks as much as possible. "
        f"The expected OCR language hint is: {lang_hint}. "
        "Do not summarize, translate, explain, or add markdown."
    )
    client = _client()
    model_name = model or os.getenv("GOOGLE_OCR_MODEL", DEFAULT_GOOGLE_OCR_MODEL)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime),
                    prompt,
                ],
            )
            return (response.text or "").strip()
        except Exception as api_error:
            msg = str(api_error)
            retryable = (
                "429" in msg
                or "quota" in msg.lower()
                or "rate" in msg.lower()
                or "temporarily" in msg.lower()
            )
            if retryable and attempt < max_retries - 1:
                time.sleep(base_delay * (2**attempt))
                continue
            if (
                "CERTIFICATE_VERIFY_FAILED" in msg
                or "unable to get local issuer certificate" in msg
            ):
                raise RuntimeError(
                    "Google OCR SSL certificate verification failed. "
                    "Install/update certifi, or set GOOGLE_API_CA_BUNDLE/SSL_CERT_FILE "
                    "in .env to your corporate/root CA bundle."
                ) from api_error
            raise RuntimeError(f"Google OCR API call failed: {msg}") from api_error


def extract_layout_from_image(
    image_path: Path | str,
    *,
    lang_hint: str = "kor",
    model: str | None = None,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> dict[str, Any]:
    """Extract OCR text and approximate normalized text bounding boxes."""
    try:
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - dependency message path
        raise RuntimeError("google-genai is required for Google OCR.") from exc

    path = Path(image_path)
    data = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    prompt = (
        "Extract all visible text from this ebook page image. "
        "Return ONLY valid JSON, with no markdown fences or explanation. "
        "Use this exact shape: "
        "{\"image_width\": number, \"image_height\": number, \"text\": string, "
        "\"blocks\": [{\"text\": string, \"bbox\": {\"x\": number, \"y\": number, "
        "\"w\": number, \"h\": number}, \"confidence\": number}]}. "
        "Each bbox must be normalized 0..1 relative to the full image, with x,y "
        "at top-left and w,h as width and height. Prefer line-level or paragraph-level "
        "blocks in reading order. "
        f"The expected OCR language hint is: {lang_hint}. "
        "Do not summarize, translate, or omit visible text."
    )
    client = _client()
    model_name = model or os.getenv("GOOGLE_OCR_MODEL", DEFAULT_GOOGLE_OCR_MODEL)
    config = None
    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
    except Exception:
        config = None

    last_layout_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            kwargs: dict[str, Any] = {
                "model": model_name,
                "contents": [
                    types.Part.from_bytes(data=data, mime_type=mime),
                    prompt,
                ],
            }
            if config is not None:
                kwargs["config"] = config
            response = client.models.generate_content(**kwargs)
            raw = _extract_json_object(response.text or "")
            return _sanitize_layout(raw, path)
        except (json.JSONDecodeError, RuntimeError) as layout_error:
            last_layout_error = layout_error
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2**attempt))
                continue
            try:
                text = extract_text_from_image(
                    path,
                    lang_hint=lang_hint,
                    model=model_name,
                    max_retries=max_retries,
                    base_delay=base_delay,
                )
                return _layout_from_plain_text(text, path)
            except Exception as fallback_error:
                raise RuntimeError(
                    "Google OCR layout API call failed and plaintext fallback failed: "
                    f"{layout_error}; fallback: {fallback_error}"
                ) from fallback_error
        except Exception as api_error:
            msg = str(api_error)
            retryable = (
                "429" in msg
                or "quota" in msg.lower()
                or "rate" in msg.lower()
                or "temporarily" in msg.lower()
                or "json" in msg.lower()
            )
            if retryable and attempt < max_retries - 1:
                time.sleep(base_delay * (2**attempt))
                continue
            if (
                "CERTIFICATE_VERIFY_FAILED" in msg
                or "unable to get local issuer certificate" in msg
            ):
                raise RuntimeError(
                    "Google OCR SSL certificate verification failed. "
                    "Install/update certifi, or set GOOGLE_API_CA_BUNDLE/SSL_CERT_FILE "
                    "in .env to your corporate/root CA bundle."
                ) from api_error
            raise RuntimeError(f"Google OCR layout API call failed: {msg}") from api_error
    if last_layout_error is not None:
        raise RuntimeError(f"Google OCR layout API call failed: {last_layout_error}")
    raise RuntimeError("Google OCR layout API call failed")
