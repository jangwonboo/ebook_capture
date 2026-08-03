"""Per-reader behavior profiles (Kindle app, Kindle Cloud, Aladin, …).

A profile bundles the capture-behavior fields that differ between e-book
readers — page-turn key, key delivery, start fit/focus, PDF trim ratios,
etc. — so a user can pick one reader and get sane defaults.

Profiles are loaded from ``reader_profiles.jsonc`` at the repo root when
present; otherwise the built-in defaults below are used. A field left ``null``
(or omitted) in a profile means "do not override".
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping

from core.config import (
    CAPTURE_SCREEN_LEFT_THIRD,
    KEY_DELIVERY_PYAUTOGUI,
    KEY_DELIVERY_SENDINPUT,
    WINDOW_CAPTURE_SCREEN,
    CaptureConfig,
    PACKAGE_ROOT,
    PdfTrim,
    load_json_file,
    normalize_key_delivery,
)

READER_PROFILES_FILENAME = "reader_profiles.jsonc"

# Fields a profile may override on ``CaptureConfig`` (None = keep existing).
_OVERRIDE_FIELDS = (
    "capture_mode",
    "next_key",
    "key_delivery",
    "reader_focus_clicks",
    "reader_focus_x_ratio",
    "reader_focus_y_ratio",
    "focus_click_settle_sec",
    "window_capture_backend",
    "use_window_client_rect",
    "hide_cursor_during_capture",
    "delay_sec",
    "target_window_title",
    "fit_on_start",
    "start_focus_clicks",
    "start_focus_x_ratio",
    "start_focus_y_ratio",
    "pdf_trim",
)


@dataclass
class ReaderProfile:
    """Reader-specific capture behavior. ``None`` fields are not applied."""

    name: str
    label: str = ""
    note: str = ""
    capture_mode: str | None = None
    next_key: str | None = None
    key_delivery: str | None = None
    reader_focus_clicks: int | None = None
    reader_focus_x_ratio: float | None = None
    reader_focus_y_ratio: float | None = None
    focus_click_settle_sec: float | None = None
    window_capture_backend: str | None = None
    use_window_client_rect: bool | None = None
    hide_cursor_during_capture: bool | None = None
    delay_sec: float | None = None
    target_window_title: str | None = None
    # Start layout: resize to primary left-third @ (0,0), then optional focus clicks.
    fit_on_start: bool | None = None
    start_focus_clicks: int | None = None
    start_focus_x_ratio: float | None = None
    start_focus_y_ratio: float | None = None
    # PDF margin trim ratios (of captured image width/height).
    pdf_trim: PdfTrim | None = None

    def apply_to(self, cfg: CaptureConfig) -> list[str]:
        """Apply set (non-None) fields onto ``cfg``; return human-readable notes."""
        changed: list[str] = []
        for field_name in _OVERRIDE_FIELDS:
            value = getattr(self, field_name)
            if value is None:
                continue
            if field_name == "key_delivery":
                value = normalize_key_delivery(str(value))
            elif field_name in ("reader_focus_clicks", "start_focus_clicks"):
                value = max(0, min(int(value), 5))
            elif field_name in ("delay_sec", "focus_click_settle_sec"):
                value = float(value)
            elif field_name in (
                "start_focus_x_ratio",
                "start_focus_y_ratio",
                "reader_focus_x_ratio",
                "reader_focus_y_ratio",
            ):
                value = max(0.0, min(float(value), 1.0))
            elif field_name == "pdf_trim":
                value = deepcopy(value) if isinstance(value, PdfTrim) else PdfTrim.from_mapping(value)
                value.validate()
            setattr(cfg, field_name, value)
            if field_name == "pdf_trim":
                changed.append(f"pdf_trim={value.as_dict()}")
            else:
                changed.append(f"{field_name}={value!r}")
        cfg.reader_profile = self.name
        return changed

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ReaderProfile:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("reader profile requires a non-empty 'name'")
        kwargs: dict[str, Any] = {"name": name}
        valid = {f.name for f in fields(cls)}
        for key, raw in data.items():
            if key == "name" or key not in valid:
                continue
            if key == "pdf_trim":
                if raw is None:
                    continue
                kwargs[key] = PdfTrim.from_mapping(raw if isinstance(raw, Mapping) else {})
            else:
                kwargs[key] = raw
        return cls(**kwargs)


def _proven_capture_defaults(pdf_trim: PdfTrim | None = None) -> dict[str, Any]:
    """Defaults proven on Kindle for PC; shared by all built-in profiles.

    Per-page loop (see ``pipeline._run_phase_capture`` / REQUIREMENTS §12):
    center clicks → park pointer → settle → capture → next_key → delay.
    """
    return {
        "capture_mode": CAPTURE_SCREEN_LEFT_THIRD,
        "window_capture_backend": WINDOW_CAPTURE_SCREEN,
        "use_window_client_rect": True,
        "hide_cursor_during_capture": True,
        "delay_sec": 2.0,
        # Capture-before focus: page center, spaced beyond double-click time.
        "reader_focus_clicks": 2,
        "reader_focus_x_ratio": 0.5,
        "reader_focus_y_ratio": 0.5,
        "focus_click_settle_sec": 1.0,
        # No start resize/focus — user positions the reader beforehand.
        "fit_on_start": False,
        "start_focus_clicks": 0,
        "start_focus_x_ratio": 0.5,
        "start_focus_y_ratio": 0.5,
        "pdf_trim": pdf_trim or PdfTrim(left=0.0, right=0.0, top=0.0, bottom=0.0),
    }


# The Kindle desktop app draws its own top bar (back arrow, settings, window
# buttons) inside the client area, so window capture always includes it. The
# bottom page-number footer ("Page X of Y") is kept (pdf_trim bottom=0).
# Ratio ~63 px on a 1799 px tall left-third capture (chrome ends at y=59).
_KINDLE_APP_TOP_BAR_RATIO = 0.035

# Kindle pages are full of activatable content — TOC entries in the center,
# figure/footnote links that can sit on any text line — so no fixed click
# point is safe. Focus via the Win32 API instead (clicks=0 → pipeline
# foregrounds the pinned window without touching the mouse).
_KINDLE_APP_FOCUS_CLICKS = 0
_KINDLE_APP_FOCUS_Y_RATIO = 0.08

# Aladin desktop: thin app title strip is cropped; the icon toolbar below it is
# white-filled (keeps top margin). Bottom page-nav is cropped. Measured on a
# 1761 px capture: title ~18 px, toolbar+pad ~45 px, bottom nav ~80 px.
_ALADIN_APP_TOP_TITLE_RATIO = 0.010
_ALADIN_APP_TOP_TOOLBAR_FILL_RATIO = 0.026
_ALADIN_APP_BOTTOM_NAV_RATIO = 0.045


# Built-in profiles. ``target_window_title`` is only set where the title is
# stable across machines (Kindle desktop app). Browser tabs vary, so those are
# left None — pick the window in the GUI or set it in the config.
#
# Only fields that *differ* from ``_proven_capture_defaults`` are set explicitly
# (next_key, key_delivery, title, pdf_trim, notes). Re-verify each profile with
# ``--debug-capture`` when tuning (see CONTEXT.md).
_BUILTIN_PROFILES: tuple[ReaderProfile, ...] = (
    ReaderProfile(
        name="kindle_app",
        label="Kindle ebook reader (desktop app)",
        note=(
            "Proven baseline. API foreground (no clicks) → capture → "
            "right/SendInput. PDF trims app top bar (client-area chrome)."
        ),
        next_key="right",
        key_delivery=KEY_DELIVERY_SENDINPUT,
        target_window_title="Kindle",
        **{
            **_proven_capture_defaults(PdfTrim(top=_KINDLE_APP_TOP_BAR_RATIO)),
            "reader_focus_clicks": _KINDLE_APP_FOCUS_CLICKS,
            "reader_focus_y_ratio": _KINDLE_APP_FOCUS_Y_RATIO,
        },
    ),
    ReaderProfile(
        name="kindle_cloud",
        label="Kindle Cloud Reader (read.amazon.com, browser)",
        note=(
            "Same loop as kindle_app; center clicks (not top — top opens Aa/zoom). "
            "Browser → pyautogui. Pick browser tab title in GUI/config. pdf_trim TBD."
        ),
        next_key="right",
        key_delivery=KEY_DELIVERY_PYAUTOGUI,
        **_proven_capture_defaults(),
    ),
    ReaderProfile(
        name="aladin_app",
        label="Aladin ebook reader (desktop app)",
        note=(
            "Window title is the book name — set target_window_title in the "
            "book config or --window-title. PageDown/SendInput. "
            "PDF: crop thin top title strip, white-fill toolbar, crop bottom nav."
        ),
        next_key="pagedown",
        key_delivery=KEY_DELIVERY_SENDINPUT,
        **_proven_capture_defaults(
            PdfTrim(
                top=_ALADIN_APP_TOP_TITLE_RATIO,
                fill_top=_ALADIN_APP_TOP_TOOLBAR_FILL_RATIO,
                bottom=_ALADIN_APP_BOTTOM_NAV_RATIO,
            )
        ),
    ),
    ReaderProfile(
        name="aladin_web",
        label="Aladin web viewer (browser)",
        note=(
            "Same loop as kindle_app; PageDown/pyautogui. "
            "Pick browser tab title in GUI/config. pdf_trim TBD."
        ),
        next_key="pagedown",
        key_delivery=KEY_DELIVERY_PYAUTOGUI,
        **_proven_capture_defaults(),
    ),
)


def bundled_reader_profiles_path() -> Path:
    return PACKAGE_ROOT / READER_PROFILES_FILENAME


def _load_profiles() -> "dict[str, ReaderProfile]":
    profiles: dict[str, ReaderProfile] = {p.name: p for p in _BUILTIN_PROFILES}
    path = bundled_reader_profiles_path()
    if path.is_file():
        try:
            data = load_json_file(path)
            raw_list = data.get("profiles", data) if isinstance(data, Mapping) else data
            if isinstance(raw_list, list):
                for entry in raw_list:
                    if isinstance(entry, Mapping):
                        prof = ReaderProfile.from_mapping(entry)
                        profiles[prof.name] = prof
        except (OSError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"invalid {path.name}: {exc}") from exc
    return profiles


def list_reader_profiles() -> list[ReaderProfile]:
    """All profiles (built-ins plus any from ``reader_profiles.jsonc``)."""
    return list(_load_profiles().values())


def reader_profile_names() -> list[str]:
    return [p.name for p in list_reader_profiles()]


def get_reader_profile(name: str) -> ReaderProfile | None:
    if not name:
        return None
    return _load_profiles().get(str(name).strip())


def apply_reader_profile(cfg: CaptureConfig, name: str) -> list[str]:
    """Apply the named profile onto ``cfg`` in place; return change notes.

    Raises ``ValueError`` if the name is unknown.
    """
    profile = get_reader_profile(name)
    if profile is None:
        available = ", ".join(reader_profile_names())
        raise ValueError(f"unknown reader profile {name!r}. Available: {available}")
    return profile.apply_to(cfg)
