"""Google Gemini OCR: lightweight structured text JSON (no layout coordinates)."""

from __future__ import annotations

import json
import os
import re
import ssl
import time
from pathlib import Path
from typing import Any

DEFAULT_GOOGLE_OCR_MODEL = "gemini-2.5-flash"

SECTION_TYPES = frozenset(
    {
        "title",
        "section_title",
        "subtitle",
        "toc",
        "body",
        "figure",
        "caption",
        "footnote",
        "header",
        "page_number",
        "other",
    }
)

_FALLBACK_PROMPT = (
    "Extract all visible text from this ebook page. "
    'Return ONLY JSON: {"page": number, "text": string, '
    '"sections": [{"type": "body|title|toc|figure|footnote|caption|header|page_number|other", "text": string}]}. '
    "Merge wrapped lines into paragraphs; do not preserve page layout line breaks. "
    "Language hint: {lang_hint}. Page: {page_num}."
)


def bundled_default_ocr_prompt_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "ocr_default_prompt.txt"


def resolve_ocr_prompt(
    *,
    lang_hint: str,
    page_num: int,
    custom_prompt: str = "",
    prompt_file: str = "",
) -> str:
    """Build the Gemini prompt from inline text, a file, or the bundled default."""
    if custom_prompt.strip():
        template = custom_prompt.strip()
    else:
        path = Path(prompt_file).expanduser() if prompt_file.strip() else bundled_default_ocr_prompt_path()
        if path.is_file():
            template = path.read_text(encoding="utf-8")
        else:
            template = _FALLBACK_PROMPT
    return (
        template.replace("{lang_hint}", lang_hint)
        .replace("{page_num}", str(page_num))
    )


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
            raise RuntimeError("Google OCR response did not contain JSON")
        raw = json.loads(cleaned[start : end + 1])
    if not isinstance(raw, dict):
        raise RuntimeError("Google OCR response must be a JSON object")
    return raw


def _normalize_section(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    section_type = str(item.get("type", "body")).strip().lower() or "body"
    if section_type not in SECTION_TYPES:
        section_type = "other"
    text = str(item.get("text", "")).strip()
    if not text:
        return None
    return {"type": section_type, "text": text}


def page_structure_to_text(data: dict[str, Any]) -> str:
    """Flatten sections into readable plain text with type headers."""
    text = str(data.get("text", "")).strip()
    if text:
        return text
    parts: list[str] = []
    for section in data.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_type = str(section.get("type", "body")).strip().lower() or "body"
        body = str(section.get("text", "")).strip()
        if body:
            parts.append(f"[{section_type.upper()}]\n{body}")
    return "\n\n".join(parts).strip()


def sanitize_page_structure(raw: dict[str, Any], page_num: int) -> dict[str, Any]:
    sections: list[dict[str, str]] = []
    for item in raw.get("sections", []):
        section = _normalize_section(item)
        if section is not None:
            sections.append(section)

    if not sections:
        fallback = str(raw.get("text", "")).strip()
        if fallback:
            sections.append({"type": "body", "text": fallback})

    if not sections:
        for key in ("blocks", "content", "paragraphs"):
            alt = raw.get(key)
            if not isinstance(alt, list):
                continue
            for item in alt:
                if isinstance(item, str) and item.strip():
                    sections.append({"type": "body", "text": item.strip()})
                elif isinstance(item, dict):
                    section = _normalize_section(
                        {
                            "type": item.get("type", "body"),
                            "text": item.get("text") or item.get("content") or "",
                        }
                    )
                    if section is not None:
                        sections.append(section)

    text = str(raw.get("text", "")).strip() or page_structure_to_text({"sections": sections})
    return {
        "page": int(raw.get("page") or page_num),
        "text": text,
        "sections": sections,
    }


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
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


def _resolve_ca_bundle_path(extra_ca: str) -> Path:
    """Resolve CA bundle path; fall back to repo root by filename if missing."""
    path = Path(extra_ca).expanduser()
    if path.is_file():
        return path
    repo_root = Path(__file__).resolve().parents[1]
    if not path.is_absolute():
        repo_relative = repo_root / path
        if repo_relative.is_file():
            return repo_relative
    fallback = repo_root / path.name
    if fallback.is_file():
        return fallback
    return path


def _ssl_context() -> ssl.SSLContext:
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

    ca_path = _resolve_ca_bundle_path(extra_ca)
    if not ca_path.is_file():
        if mode == "certifi":
            return ctx
        raise RuntimeError(f"Google OCR CA bundle not found: {ca_path}")

    data = ca_path.read_bytes()
    try:
        if b"-----BEGIN CERTIFICATE-----" in data:
            ctx.load_verify_locations(cafile=str(ca_path))
        else:
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
    except ImportError as exc:
        raise RuntimeError("google-genai is required for Google OCR.") from exc

    ctx = _ssl_context()
    http_options = types.HttpOptions(
        client_args={"verify": ctx},
        async_client_args={"verify": ctx},
    )
    return genai.Client(api_key=api_key, http_options=http_options)


def _call_gemini_json_bytes(
    data: bytes,
    mime: str,
    prompt: str,
    *,
    model: str | None = None,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> dict[str, Any]:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai is required for Google OCR.") from exc

    client = _client()
    model_name = model or os.getenv("GOOGLE_OCR_MODEL", DEFAULT_GOOGLE_OCR_MODEL)
    config = None
    try:
        config = types.GenerateContentConfig(response_mime_type="application/json")
    except Exception:
        config = None

    last_error: Exception | None = None
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
            return _extract_json_object(response.text or "")
        except (json.JSONDecodeError, RuntimeError) as parse_error:
            last_error = parse_error
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2**attempt))
                continue
            raise RuntimeError(f"Google OCR JSON parse failed: {parse_error}") from parse_error
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
            raise RuntimeError(f"Google OCR API call failed: {msg}") from api_error
    if last_error is not None:
        raise RuntimeError(f"Google OCR API call failed: {last_error}")
    raise RuntimeError("Google OCR API call failed")


def _call_gemini_json(
    image_path: Path,
    prompt: str,
    *,
    model: str | None = None,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> dict[str, Any]:
    path = Path(image_path)
    data = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return _call_gemini_json_bytes(
        data,
        mime,
        prompt,
        model=model,
        max_retries=max_retries,
        base_delay=base_delay,
    )


def extract_page_structure_from_pdf_page(
    pdf_path: Path | str,
    page_index: int,
    *,
    page_num: int = 1,
    lang_hint: str = "kor",
    prompt: str = "",
    prompt_file: str = "",
    model: str | None = None,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> dict[str, Any]:
    """Extract structured OCR JSON from one page of a PDF (0-based page_index)."""
    from core.pdf_input import extract_pdf_page_bytes

    resolved_prompt = resolve_ocr_prompt(
        lang_hint=lang_hint,
        page_num=page_num,
        custom_prompt=prompt,
        prompt_file=prompt_file,
    )
    page_pdf = extract_pdf_page_bytes(pdf_path, page_index)
    raw = _call_gemini_json_bytes(
        page_pdf,
        "application/pdf",
        resolved_prompt,
        model=model,
        max_retries=max_retries,
        base_delay=base_delay,
    )
    result = sanitize_page_structure(raw, page_num)
    if not result["text"] and not result["sections"]:
        raw = _call_gemini_json_bytes(
            page_pdf,
            "application/pdf",
            resolved_prompt,
            model=model,
            max_retries=max_retries,
            base_delay=base_delay,
        )
        result = sanitize_page_structure(raw, page_num)
    return result


def extract_page_structure_from_image(
    image_path: Path | str,
    *,
    page_num: int = 1,
    lang_hint: str = "kor",
    prompt: str = "",
    prompt_file: str = "",
    model: str | None = None,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> dict[str, Any]:
    """Extract lightweight structured OCR JSON (sections without coordinates)."""
    path = Path(image_path)
    resolved_prompt = resolve_ocr_prompt(
        lang_hint=lang_hint,
        page_num=page_num,
        custom_prompt=prompt,
        prompt_file=prompt_file,
    )
    raw = _call_gemini_json(
        path,
        resolved_prompt,
        model=model,
        max_retries=max_retries,
        base_delay=base_delay,
    )
    result = sanitize_page_structure(raw, page_num)
    if not result["text"] and not result["sections"]:
        raw = _call_gemini_json(
            path,
            resolved_prompt,
            model=model,
            max_retries=max_retries,
            base_delay=base_delay,
        )
        result = sanitize_page_structure(raw, page_num)
    return result


def extract_text_from_image(
    image_path: Path | str,
    *,
    page_num: int = 1,
    lang_hint: str = "kor",
    prompt: str = "",
    prompt_file: str = "",
    model: str | None = None,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> str:
    """Return flattened page text from structured OCR."""
    data = extract_page_structure_from_image(
        image_path,
        page_num=page_num,
        lang_hint=lang_hint,
        prompt=prompt,
        prompt_file=prompt_file,
        model=model,
        max_retries=max_retries,
        base_delay=base_delay,
    )
    return page_structure_to_text(data)
