"""Enumerate / activate host windows and derive capture rectangles (Windows-focused)."""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

try:
    import pygetwindow as gw  # type: ignore
except ImportError:
    gw = None


def window_support_available() -> bool:
    return gw is not None and sys.platform == "win32"


def list_window_titles() -> list[str]:
    """Visible top-level windows with non-empty titles, sorted."""
    if not window_support_available():
        return []
    titles: list[str] = []
    try:
        for w in gw.getAllWindows():
            try:
                t = (w.title or "").strip()
                if not t:
                    continue
                if getattr(w, "visible", True) is False:
                    continue
                titles.append(t)
            except Exception:
                continue
    except Exception:
        return []
    return sorted(set(titles))


def resolve_target_window(title: str, *, prefer_foreground: bool = True):
    """Resolve one window from a case-insensitive substring title query.

    We do explicit substring filtering over all visible windows rather than relying on
    ``pygetwindow.getWindowsWithTitle`` behavior, so partial title queries are stable.

    If multiple windows match:
    - Prefer the **foreground** window when requested.
    - Else prefer an exact title match (case-insensitive).
    - Else fall back to first enumeration order.
    """
    if not window_support_available() or not title.strip():
        raise RuntimeError("Window capture is not available on this platform")
    assert gw is not None
    key = title.strip().casefold()
    wins = []
    try:
        for w in gw.getAllWindows():
            try:
                w_title = (w.title or "").strip()
                if not w_title:
                    continue
                if getattr(w, "visible", True) is False:
                    continue
                if key in w_title.casefold():
                    wins.append(w)
            except Exception:
                continue
    except Exception as ex:
        raise RuntimeError(f"Window enumeration failed: {ex}") from ex
    if not wins:
        raise RuntimeError(f"Window not found: {title!r}")
    if len(wins) == 1:
        return wins[0]
    if prefer_foreground:
        try:
            active = gw.getActiveWindow()
        except Exception:
            active = None
        if active is not None:
            for w in wins:
                if w == active:
                    return w
    for w in wins:
        if (w.title or "").strip().casefold() == key:
            return w
    return wins[0]


def _hwnd_int(win: object) -> int:
    return int(getattr(win, "_hWnd", 0))


def resolve_target_hwnd(title: str, *, prefer_foreground: bool = True) -> int:
    """HWND of the window chosen by ``resolve_target_window``."""
    w = resolve_target_window(title, prefer_foreground=prefer_foreground)
    h = _hwnd_int(w)
    if h == 0:
        raise RuntimeError("Resolved window has no HWND")
    return h


class _WINDOWINFO(ctypes.Structure):
    """TAG WINDOWINFO — rcClient is already in **screen** coordinates (see GetWindowInfo)."""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcWindow", wintypes.RECT),
        ("rcClient", wintypes.RECT),
        ("dwStyle", wintypes.DWORD),
        ("dwExStyle", wintypes.DWORD),
        ("dwWindowStatus", wintypes.DWORD),
        ("cxWindowBorders", wintypes.UINT),
        ("cyWindowBorders", wintypes.UINT),
        ("atomWindowType", ctypes.c_uint16),
        ("wCreatorVersion", ctypes.c_uint16),
    ]


def _client_area_via_getwindowinfo(hwnd: int) -> tuple[int, int, int, int] | None:
    """Preferred: GetWindowInfo.rcClient matches OS compositor / screen capture space."""
    user32 = ctypes.windll.user32
    wi = _WINDOWINFO()
    wi.cbSize = ctypes.sizeof(_WINDOWINFO)
    if not user32.GetWindowInfo(hwnd, ctypes.byref(wi)):
        return None
    rc = wi.rcClient
    left, top = int(rc.left), int(rc.top)
    width = int(rc.right - rc.left)
    height = int(rc.bottom - rc.top)
    if width < 1 or height < 1:
        return None
    return left, top, width, height


def _client_area_via_getclientrect(hwnd: int) -> tuple[int, int, int, int]:
    """Legacy: GetClientRect + ClientToScreen (can disagree with GetWindowInfo under DPI)."""
    user32 = ctypes.windll.user32
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        raise OSError("GetClientRect failed")
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    left, top = int(pt.x), int(pt.y)
    width = int(r.right - r.left)
    height = int(r.bottom - r.top)
    if width < 1 or height < 1:
        raise ValueError("client area has non-positive size")
    return left, top, width, height


def client_area_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Client area in **screen** pixels — aligned with GDI/mss capture when possible."""
    if sys.platform != "win32" or hwnd == 0:
        raise RuntimeError("client_area_screen_rect requires a Windows HWND")
    got = _client_area_via_getwindowinfo(hwnd)
    if got is not None:
        return got
    return _client_area_via_getclientrect(hwnd)


def client_area_wh_for_hwnd(hwnd: int) -> tuple[int, int]:
    """Client width × height in pixels (same basis as ``client_area_screen_rect`` / pointer region)."""
    _l, _t, w, h = client_area_screen_rect(hwnd)
    return w, h


def frame_screen_rect(win: object) -> tuple[int, int, int, int]:
    """Outer window rect from pygetwindow (includes title bar and borders)."""
    return int(win.left), int(win.top), int(win.width), int(win.height)


def print_active_window_rects() -> str:
    """Print ``ACTIVE_WIN`` lines to stdout, then return the title for ``target_window_title``.

    Intended for CLI ``--active-window``: log Remote Desktop (or any) foreground window
    coords, then capture using that title as the substring match.

    Raises:
        RuntimeError: Not Windows / missing dependency / no foreground window / empty title.
    """
    if not window_support_available():
        raise RuntimeError(
            "Active window probe requires Windows with pygetwindow installed."
        )
    assert gw is not None
    aw = gw.getActiveWindow()
    if aw is None:
        raise RuntimeError("No foreground window.")
    title = (aw.title or "").strip()
    if not title:
        raise RuntimeError("Foreground window has an empty title.")
    hwnd = _hwnd_int(aw)
    fl, ft, fw, fh = frame_screen_rect(aw)
    print(f"ACTIVE_WIN title={title!r}", flush=True)
    print(f"ACTIVE_WIN hwnd_dec={hwnd} hwnd_hex=0x{hwnd:x}", flush=True)
    print(
        f"ACTIVE_WIN frame_outer left={fl} top={ft} width={fw} height={fh}",
        flush=True,
    )
    gwi = _client_area_via_getwindowinfo(hwnd)
    if gwi is not None:
        l, t, w, h = gwi
        print(
            f"ACTIVE_WIN client_screen left={l} top={t} width={w} height={h} "
            f"(right={l + w} bottom={t + h})  [capture uses this when use_window_client_rect]",
            flush=True,
        )
    else:
        print("ACTIVE_WIN client_screen GetWindowInfo FAILED", flush=True)
    try:
        cl, ct, cw, ch = _client_area_via_getclientrect(hwnd)
        print(
            f"ACTIVE_WIN client_legacy left={cl} top={ct} width={cw} height={ch}",
            flush=True,
        )
    except Exception as ex:
        print(f"ACTIVE_WIN client_legacy FAILED {ex!r}", flush=True)
    return title


def _base_rect_from_resolved_window(
    win: object,
    *,
    use_client_rect: bool,
) -> tuple[int, int, int, int]:
    """Same basis as capture: client area or outer frame."""
    if use_client_rect and sys.platform == "win32":
        try:
            return client_area_screen_rect(_hwnd_int(win))
        except Exception:
            pass
    return frame_screen_rect(win)


def get_window_metrics(
    title: str,
    *,
    use_client_rect: bool = True,
    prefer_foreground: bool = True,
) -> tuple[int, int, int, int]:
    """Return left, top, width, height in screen coordinates.

    ``use_client_rect`` matches what you see inside the window frame (recommended for
    Remote Desktop: captures only the remote desktop surface, not the local title bar).
    """
    if not window_support_available():
        raise RuntimeError("Window capture is not available on this platform")
    w = resolve_target_window(title, prefer_foreground=prefer_foreground)
    return _base_rect_from_resolved_window(w, use_client_rect=use_client_rect)


def debug_rect_lines_window_capture(
    target_window_title: str,
    capture_mode: str,
    *,
    use_client_rect: bool,
    prefer_foreground: bool,
) -> list[str]:
    """Human-readable lines: outer frame, client area, preset base, final crop (screen px)."""
    if not window_support_available():
        return ["DEBUG_RECT window_util unavailable (not Windows / pygetwindow)"]
    w = resolve_target_window(
        target_window_title,
        prefer_foreground=prefer_foreground,
    )
    hwnd = _hwnd_int(w)
    fl, ft, fw, fh = frame_screen_rect(w)
    full_title = (w.title or "").replace("\n", " ")
    gwi = _client_area_via_getwindowinfo(hwnd)
    if gwi is not None:
        gl, gt, gw, gh = gwi
        gwi_msg = (
            f"DEBUG_RECT client_GetWindowInfo left={gl} top={gt} width={gw} height={gh} "
            f"(right={gl + gw} bottom={gt + gh}) [used for capture]"
        )
    else:
        gwi_msg = "DEBUG_RECT client_GetWindowInfo FAILED"
    gcr_result: tuple[int, int, int, int] | None = None
    try:
        gcr_result = _client_area_via_getclientrect(hwnd)
        cl, ct, cw, ch = gcr_result
        gcr_msg = (
            f"DEBUG_RECT client_GetClientRect+ClientToScreen left={cl} top={ct} "
            f"width={cw} height={ch} (right={cl + cw} bottom={ct + ch}) [legacy]"
        )
    except Exception as ex:
        gcr_msg = f"DEBUG_RECT client_GetClientRect failed ({ex!r})"

    delta_msg = ""
    if gwi is not None and gcr_result is not None:
        gl, gt, gw, gh = gwi
        cl, ct, cw, ch = gcr_result
        delta_msg = (
            f"DEBUG_RECT client_delta(GetWindowInfo minus legacy) "
            f"d_left={gl - cl} d_top={gt - ct} d_width={gw - cw} d_height={gh - ch}"
        )

    if gwi is not None:
        client_msg = (
            "DEBUG_RECT client_source=GetWindowInfo.rcClient "
            "(preferred vs GetClientRect for DPI/y-offset issues)"
        )
    else:
        client_msg = "DEBUG_RECT client_source=GetClientRect+ClientToScreen fallback"

    bl, bt, bw, bh = _base_rect_from_resolved_window(
        w,
        use_client_rect=use_client_rect,
    )
    pl, pt, pw, ph = rect_for_capture_mode(bl, bt, bw, bh, capture_mode)
    return [
        f"DEBUG_RECT query_substring={target_window_title!r}",
        f"DEBUG_RECT resolved_title={full_title!r}",
        f"DEBUG_RECT hwnd_dec={hwnd} hwnd_hex=0x{hwnd:x}",
        f"DEBUG_RECT frame_outer left={fl} top={ft} width={fw} height={fh}",
        gwi_msg,
        gcr_msg,
        *([delta_msg] if delta_msg else []),
        client_msg,
        f"DEBUG_RECT preset_base left={bl} top={bt} width={bw} height={bh} "
        f"(use_client_rect={use_client_rect})",
        f"DEBUG_RECT capture_mode={capture_mode}",
        f"DEBUG_RECT crop_screen left={pl} top={pt} width={pw} height={ph}  "
        f"(right={pl + pw} bottom={pt + ph})",
    ]


def activate_window_title(
    title: str,
    *,
    prefer_foreground: bool = True,
) -> bool:
    """Bring the resolved matching window to the foreground."""
    if not window_support_available() or not title.strip():
        return False
    try:
        w = resolve_target_window(title, prefer_foreground=prefer_foreground)
        if getattr(w, "isMinimized", False):
            try:
                w.restore()
            except Exception:
                pass
        w.activate()
        time.sleep(0.12)
        return True
    except Exception:
        return False


def rect_for_capture_mode(
    left: int,
    top: int,
    width: int,
    height: int,
    capture_mode: str,
) -> tuple[int, int, int, int]:
    """Apply horizontal third presets; vertical uses full window height."""
    if capture_mode in ("manual", "window_full"):
        return left, top, width, height
    if capture_mode == "window_left_third":
        w3 = max(1, width // 3)
        return left, top, w3, height
    if capture_mode == "window_right_third":
        w3 = max(1, width // 3)
        rem = max(1, width - 2 * w3)
        return left + 2 * w3, top, rem, height
    return left, top, width, height


def resolve_screen_rect(
    target_window_title: str,
    capture_mode: str,
    *,
    use_client_rect: bool = True,
    prefer_foreground: bool = True,
) -> tuple[int, int, int, int]:
    """Live window rect adjusted for capture_mode."""
    L, T, W, H = get_window_metrics(
        target_window_title,
        use_client_rect=use_client_rect,
        prefer_foreground=prefer_foreground,
    )
    return rect_for_capture_mode(L, T, W, H, capture_mode)
