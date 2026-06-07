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


def _win32_modules() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    return ctypes.windll.user32, ctypes.windll.kernel32  # type: ignore[attr-defined]


def foreground_hwnd() -> int:
    """HWND of the current foreground window (0 if unavailable)."""
    if sys.platform != "win32":
        return 0
    user32, _ = _win32_modules()
    return int(user32.GetForegroundWindow())


def is_foreground_hwnd(hwnd: int) -> bool:
    return hwnd > 0 and foreground_hwnd() == hwnd


def _unlock_foreground_for_automation() -> None:
    """Work around Windows SetForegroundWindow restrictions from background tools."""
    if sys.platform != "win32":
        return
    user32, _ = _win32_modules()
    ASFW_ANY = 0xFFFFFFFF
    user32.AllowSetForegroundWindow(ASFW_ANY)
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)


def force_foreground_hwnd(hwnd: int) -> bool:
    """Bring ``hwnd`` to the foreground (Chrome/RDP need more than pygetwindow.activate)."""
    if sys.platform != "win32" or hwnd <= 0:
        return False
    _unlock_foreground_for_automation()
    user32, kernel32 = _win32_modules()
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() == hwnd:
        return True

    foreground = user32.GetForegroundWindow()
    if foreground == hwnd:
        return True

    pid = wintypes.DWORD()
    fg_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
    target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    current_thread = kernel32.GetCurrentThreadId()

    attached_fg = bool(user32.AttachThreadInput(current_thread, fg_thread, True))
    attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)
        if attached_fg:
            user32.AttachThreadInput(current_thread, fg_thread, False)

    return user32.GetForegroundWindow() == hwnd


def foreground_window_title() -> str:
    """Title of the current foreground window (empty if unavailable)."""
    if sys.platform != "win32":
        return ""
    user32, _ = _win32_modules()
    hwnd = int(user32.GetForegroundWindow())
    if hwnd == 0:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def focus_window_for_keyboard(hwnd: int) -> bool:
    """Foreground the window for keyboard input without moving or clicking the mouse."""
    if sys.platform != "win32" or hwnd <= 0:
        return False
    user32, _ = _win32_modules()
    if not force_foreground_hwnd(hwnd):
        return False
    child = find_browser_content_hwnd(hwnd)
    focus_hwnd = child if child else hwnd
    try:
        user32.SetFocus(focus_hwnd)
    except Exception:
        pass
    try:
        user32.SwitchToThisWindow(hwnd, True)
    except Exception:
        pass
    time.sleep(0.12)
    return is_foreground_hwnd(hwnd)


_VK_BY_KEY: dict[str, int] = {
    "right": 0x27,
    "left": 0x25,
    "up": 0x26,
    "down": 0x28,
    "pagedown": 0x22,
    "pageup": 0x21,
    "home": 0x24,
    "end": 0x23,
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ii", _INPUTUNION),
    ]


def _vk_for_key(key: str) -> int | None:
    return _VK_BY_KEY.get(str(key or "").strip().lower())


def find_browser_content_hwnd(top_hwnd: int) -> int | None:
    """Largest visible Chrome/Edge renderer child HWND, if any."""
    if sys.platform != "win32" or top_hwnd <= 0:
        return None
    user32, _ = _win32_modules()
    best_hwnd: int | None = None
    best_area = 0
    target_classes = (
        "Chrome_RenderWidgetHostHWND",
        "Chrome_WidgetWin_0",
        "MozillaWindowClass",
    )

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        nonlocal best_hwnd, best_area
        if not user32.IsWindowVisible(hwnd):
            return True
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls = cls_buf.value
        if not any(token in cls for token in target_classes):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        if area > best_area:
            best_area = area
            best_hwnd = int(hwnd)
        return True

    user32.EnumChildWindows(top_hwnd, enum_proc, 0)
    return best_hwnd


def _sendinput_vk(vk: int) -> bool:
    if sys.platform != "win32":
        return False
    user32, _ = _win32_modules()
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    extra = ctypes.c_ulong(0)
    extra_ptr = ctypes.pointer(extra)
    inputs = (_INPUT * 2)()
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].ii.ki = _KEYBDINPUT(vk, 0, 0, 0, extra_ptr)
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].ii.ki = _KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, extra_ptr)
    sent = int(user32.SendInput(2, ctypes.byref(inputs[0]), ctypes.sizeof(_INPUT)))
    return sent == 2


def _reader_focus_tap(
    left: int,
    top: int,
    width: int,
    height: int,
    y_ratio: float,
) -> tuple[int, int]:
    """Tap upper reader body (not bottom status bar) so the tab accepts keyboard."""
    import pyautogui

    x = left + max(1, width // 2)
    y = top + max(1, int(height * max(0.05, min(y_ratio, 0.45))))
    pyautogui.click(x, y)
    time.sleep(0.08)
    return x, y


def send_page_turn_key(
    key: str,
    *,
    pinned_hwnd: int = 0,
    title: str = "",
    prefer_foreground: bool = True,
    capture_rect: tuple[int, int, int, int] | None = None,
    reader_focus_y_ratio: float = 0.15,
) -> tuple[bool, str]:
    """Foreground target window/tab and send ``key`` (SendInput). Returns (ok, log detail)."""
    if sys.platform != "win32":
        return False, "not Windows"
    vk = _vk_for_key(key)
    if vk is None:
        return False, f"unknown key {key!r}"

    try:
        hwnd = (
            pinned_hwnd
            if pinned_hwnd > 0
            else resolve_target_hwnd(title, prefer_foreground=prefer_foreground)
        )
    except Exception as ex:
        return False, f"resolve hwnd failed: {ex}"

    if not focus_window_for_keyboard(hwnd):
        return False, f"foreground failed hwnd=0x{hwnd:x}"

    parts = [f"hwnd=0x{hwnd:x}", f"foreground={foreground_window_title()!r}"]

    if reader_focus_y_ratio > 0 and capture_rect is not None:
        l, t, w, h = capture_rect
        if w > 0 and h > 0:
            tx, ty = _reader_focus_tap(l, t, w, h, reader_focus_y_ratio)
            parts.append(f"reader_tap=({tx},{ty}) y_ratio={reader_focus_y_ratio}")

    key_name = str(key).strip().lower()
    via = "SendInput"
    if _sendinput_vk(vk):
        parts.append(f"vk=0x{vk:02x}")
    else:
        import pyautogui

        pyautogui.press(key_name)
        via = "pyautogui"
        parts.append("SendInput_fallback")

    return True, "; ".join(parts + [f"via={via}"])


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


def window_for_hwnd(hwnd: int):
    """Return the pygetwindow object for a known HWND."""
    if not window_support_available() or hwnd <= 0:
        raise RuntimeError("Window capture is not available on this platform")
    assert gw is not None
    for w in gw.getAllWindows():
        try:
            if _hwnd_int(w) == hwnd:
                return w
        except Exception:
            continue
    raise RuntimeError(f"Window HWND not found: 0x{hwnd:x}")


def get_window_metrics_for_hwnd(
    hwnd: int,
    *,
    use_client_rect: bool = True,
) -> tuple[int, int, int, int]:
    """Return left, top, width, height for a pinned HWND."""
    w = window_for_hwnd(hwnd)
    return _base_rect_from_resolved_window(w, use_client_rect=use_client_rect)


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
    pinned_hwnd: int = 0,
) -> bool:
    """Bring the resolved matching window to the foreground."""
    if not window_support_available() or not title.strip():
        return False
    try:
        hwnd = (
            pinned_hwnd
            if pinned_hwnd > 0
            else resolve_target_hwnd(title, prefer_foreground=prefer_foreground)
        )
        if focus_window_for_keyboard(hwnd):
            return True
        w = window_for_hwnd(hwnd)
        if getattr(w, "isMinimized", False):
            try:
                w.restore()
            except Exception:
                pass
        w.activate()
        time.sleep(0.15)
        return is_foreground_hwnd(hwnd)
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
    pinned_hwnd: int = 0,
) -> tuple[int, int, int, int]:
    """Live window rect adjusted for capture_mode."""
    if pinned_hwnd > 0:
        L, T, W, H = get_window_metrics_for_hwnd(
            pinned_hwnd,
            use_client_rect=use_client_rect,
        )
    else:
        L, T, W, H = get_window_metrics(
            target_window_title,
            use_client_rect=use_client_rect,
            prefer_foreground=prefer_foreground,
        )
    return rect_for_capture_mode(L, T, W, H, capture_mode)


def pin_target_window(
    target_window_title: str,
    *,
    prefer_foreground: bool = True,
) -> tuple[int, str]:
    """Activate matching window and return (hwnd, full title) for the whole capture run."""
    if not window_support_available() or not target_window_title.strip():
        raise RuntimeError("Window capture is not available on this platform")
    activate_window_title(
        target_window_title,
        prefer_foreground=prefer_foreground,
    )
    w = resolve_target_window(
        target_window_title,
        prefer_foreground=prefer_foreground,
    )
    hwnd = _hwnd_int(w)
    if hwnd == 0:
        raise RuntimeError("Resolved window has no HWND")
    force_foreground_hwnd(hwnd)
    time.sleep(0.1)
    return hwnd, (w.title or "").strip()
