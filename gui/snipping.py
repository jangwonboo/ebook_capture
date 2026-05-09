"""Fullscreen dim overlay to pick a capture rectangle (blocks until selection completes)."""

from __future__ import annotations

import sys

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QGuiApplication, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QRubberBand,
    QPushButton,
    QSplashScreen,
)


class SnippingWidget(QSplashScreen):
    """Dim fullscreen overlay; drag to select a rectangle."""

    regionSelected = pyqtSignal()
    regionCancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.origin = QPoint(0, 0)
        self.end = QPoint(0, 0)
        self._aborted = False
        self._released = False
        self._dragging = False
        self.rubberBand = QRubberBand(QRubberBand.Rectangle, self)
        self.createDimScreenEffect()
        self.setFocusPolicy(Qt.StrongFocus)

    def createDimScreenEffect(self) -> None:
        self.screen = QGuiApplication.primaryScreen()
        geo = self.screen.geometry()
        screen_pix = QPixmap(geo.width(), geo.height())
        screen_pix.fill(QColor(0, 0, 0))
        self.setPixmap(screen_pix)
        self.setGeometry(geo)
        self.setWindowState(Qt.WindowFullScreen)
        self.setWindowOpacity(0.4)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.origin = event.pos()
            self.rubberBand.setGeometry(QRect(self.origin, QSize()))
            self.rubberBand.show()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.rubberBand.setGeometry(QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.end = event.pos()
            self.rubberBand.hide()
            self.hide()
            self._released = True
            self.regionSelected.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._aborted = True
            self._dragging = False
            self.rubberBand.hide()
            self.hide()
            self.regionCancelled.emit()
        else:
            super().keyPressEvent(event)

    def getCoords(self) -> tuple[QPoint, QPoint]:
        return self.origin, self.end

    def getRect(self) -> QRect:
        return QRect(self.origin, self.end).normalized()

    def was_aborted(self) -> bool:
        return self._aborted

    def was_completed(self) -> bool:
        return self._released and not self._aborted


if __name__ == "__main__":

    class SnippingTool(QMainWindow):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.btn_screenCap = QPushButton("Start capturing")
            self.btn_screenCap.clicked.connect(self.screenCapture)
            self.setCentralWidget(self.btn_screenCap)
            self.dimScreen = SnippingWidget()

        def screenCapture(self) -> None:
            self.dimScreen.show()

    app = QApplication(sys.argv)
    win = SnippingTool()
    win.show()
    app.exec_()
