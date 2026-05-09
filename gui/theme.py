"""Material-style Qt themes via qt-material (optional fallback)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt5.QtWidgets import QApplication


def apply_material_theme(app: "QApplication", *, dark: bool = True) -> bool:
    """Apply qt-material stylesheet. Returns True if applied."""
    try:
        # Ensure QtGui is initialized before qt-material (avoids QFontDatabase warnings).
        from PyQt5 import QtGui  # noqa: F401

        from qt_material import apply_stylesheet

        theme = "dark_blue.xml" if dark else "light_blue.xml"
        apply_stylesheet(app, theme=theme)
        return True
    except ImportError:
        app.setStyle("Fusion")
        return False
