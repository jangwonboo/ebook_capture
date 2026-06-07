"""Material-style Qt themes via qt-material (optional fallback)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt5.QtWidgets import QApplication


def apply_material_theme(app: "QApplication", *, dark: bool = True) -> bool:
    """Apply qt-material stylesheet. Returns True if applied."""
    try:
        # qt-material 2.15+ targets Qt6 only; PyQt5 needs 2.14.x (see pyproject pin).
        from PyQt5 import QtGui  # noqa: F401
        from PyQt5.QtWidgets import QApplication  # noqa: F401 — must precede qt_material

        import qt_material
        if not getattr(qt_material, "GUI", True):
            raise ImportError("qt-material has no PyQt5 bindings")

        from qt_material import apply_stylesheet

        theme = "dark_blue.xml" if dark else "light_blue.xml"
        apply_stylesheet(app, theme=theme)
        return True
    except ImportError:
        app.setStyle("Fusion")
        return False
