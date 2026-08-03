"""Windows-native look & feel for the Qt GUI."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt5.QtWidgets import QApplication


def apply_native_theme(app: "QApplication") -> str:
    """Apply the platform-native style and system UI font.

    On Windows this selects the ``windowsvista`` style (the native themed
    controls) and the Segoe UI system font; elsewhere it falls back to
    Fusion. Returns the name of the style that was applied.
    """
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import QStyleFactory

    available = {name.lower(): name for name in QStyleFactory.keys()}
    if sys.platform == "win32" and "windowsvista" in available:
        style = available["windowsvista"]
    else:
        style = available.get("fusion", next(iter(available.values())))
    app.setStyle(style)

    if sys.platform == "win32":
        font = QFont("Segoe UI")
        font.setPointSize(9)  # Windows default UI size
        app.setFont(font)

    return style
