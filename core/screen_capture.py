"""Screen region capture with Windows-specific fixes (multi-monitor, DPI)."""

from __future__ import annotations

import sys

from PIL import Image

_win32_env_ready = False


def ensure_windows_capture_environment() -> None:
    """Align GDI screen capture with Win32 window rects (pygetwindow) / virtual desktop."""
    global _win32_env_ready
    if sys.platform != "win32":
        return
    import ctypes

    if not _win32_env_ready:
        _win32_env_ready = True
        try:
            # Prefer per-monitor v2 so GetWindowRect matches multi-monitor + scaling.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    # Process-level awareness may already be locked to system-aware (e.g. an earlier
    # SetProcessDPIAware from pyautogui/mss). Then window rects on a monitor whose
    # scale differs from the primary come back DPI-virtualized while mss/GDI grabs
    # physical pixels — the capture shifts and picks up black off-window margins.
    # A thread-level per-monitor-v2 context overrides the process default (Win10+),
    # so re-apply it every call: it must hold on the thread doing rect queries.
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass


def screenshot_region(left: int, top: int, width: int, height: int) -> Image.Image:
    """
    Capture a rectangle in **virtual screen** coordinates (same space as pygetwindow).

    On Windows, the default PyAutoGUI/Pillow path uses ``all_screens=False``, which only
    grabs the primary monitor. Cropping a region on another monitor then yields black
    images. This function grabs the full virtual desktop (or uses mss) before cropping.
    """
    if width < 1 or height < 1:
        raise ValueError("screenshot width and height must be positive")

    ensure_windows_capture_environment()

    if sys.platform == "win32":
        try:
            import mss

            with mss.mss() as sct:
                mon = {"left": left, "top": top, "width": width, "height": height}
                shot = sct.grab(mon)
            return Image.frombytes("RGB", shot.size, shot.rgb)
        except ImportError:
            pass
        except Exception:
            # Fall back to Pillow path (e.g. odd MSS failures).
            pass

        import pyautogui

        return pyautogui.screenshot(
            region=(left, top, width, height),
            allScreens=True,
        )

    import pyautogui

    return pyautogui.screenshot(region=(left, top, width, height))
