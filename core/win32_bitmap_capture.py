"""Capture a window's client area via HWND (PrintWindow / BitBlt), not screen coordinates."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PIL import Image

from core.windows_util import (
    rect_for_capture_mode,
)

PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _hbitmap_to_rgb(hbmp: int, width: int, height: int) -> Image.Image | None:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetDC(0)
    if not hdc:
        return None
    try:
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = BI_RGB
        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        lines = gdi32.GetDIBits(
            hdc, hbmp, 0, height, buf, ctypes.byref(bmi), DIB_RGB_COLORS
        )
        if lines == 0:
            return None
        return Image.frombytes("RGB", (width, height), buf.raw, "raw", "BGRX")
    finally:
        user32.ReleaseDC(0, hdc)


def capture_client_printwindow(hwnd: int) -> Image.Image | None:
    """Return client-area RGB image, or None on failure (Win32 only)."""
    if sys.platform != "win32" or hwnd == 0:
        return None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # For PrintWindow, use the HWND's own client coordinate space. Do not use
    # screen/physical GetWindowInfo dimensions here; MSTSC can expose a scaled
    # physical client rect while rendering the remote framebuffer in logical px.
    rc = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    w = int(rc.right - rc.left)
    h = int(rc.bottom - rc.top)
    if w < 1 or h < 1:
        return None

    hdc_win = user32.GetDC(hwnd)
    if not hdc_win:
        return None
    hdc_mem = 0
    hbmp = 0
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
        if not hdc_mem:
            return None
        hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
        if not hbmp:
            return None
        old = gdi32.SelectObject(hdc_mem, hbmp)
        try:
            flags = PW_RENDERFULLCONTENT | PW_CLIENTONLY
            if not user32.PrintWindow(hwnd, hdc_mem, flags):
                if not gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_win, 0, 0, SRCCOPY):
                    return None
        finally:
            gdi32.SelectObject(hdc_mem, old)
        return _hbitmap_to_rgb(hbmp, w, h)
    finally:
        if hbmp:
            gdi32.DeleteObject(hbmp)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        if hdc_win:
            user32.ReleaseDC(hwnd, hdc_win)


def is_mostly_black(img: Image.Image, mean_threshold: float = 14.0) -> bool:
    """Heuristic for PrintWindow returning an empty/black buffer on some GPU paths."""
    small = img.convert("RGB").resize((max(1, img.width // 16), max(1, img.height // 16)))
    px = list(small.getdata())
    if not px:
        return True
    total = sum(sum(p) for p in px)
    mean = total / (len(px) * 3.0)
    return mean < mean_threshold


def apply_window_preset_crop(img: Image.Image, capture_mode: str) -> Image.Image:
    """Same crop box as ``resolve_screen_rect`` / mss path: ``rect_for_capture_mode(0,0,W,H,mode)``."""
    W, H = img.size
    L, T, cw, ch = rect_for_capture_mode(0, 0, W, H, capture_mode)
    return img.crop((L, T, L + cw, T + ch))
