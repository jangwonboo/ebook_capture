"""Screen region capture with Windows-specific fixes (multi-monitor, DPI)."""

from __future__ import annotations

import sys

from PIL import Image

_win32_env_ready = False


def ensure_windows_capture_environment() -> None:
    """Align GDI screen capture with Win32 window rects (pygetwindow) / virtual desktop."""
    global _win32_env_ready
    if _win32_env_ready or sys.platform != "win32":
        return
    _win32_env_ready = True
    try:
        import ctypes

        # Prefer per-monitor v2 so GetWindowRect matches multi-monitor + scaling.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
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
