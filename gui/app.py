"""Main dialog: collects options and runs the CLI capture subprocess."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
from PyQt5.QtCore import QEventLoop, QProcess, QProcessEnvironment, QRect, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QDialog,
    QMessageBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
)

from core.config import (
    CAPTURE_MANUAL,
    CAPTURE_SCREEN_LEFT_THIRD,
    CAPTURE_WINDOW_FULL,
    CAPTURE_WINDOW_LEFT_THIRD,
    CAPTURE_WINDOW_RIGHT_THIRD,
    CaptureConfig,
    DEFAULT_BOOK_TITLE,
    KEY_DELIVERY_AUTO,
    KEY_DELIVERY_POSTMESSAGE,
    KEY_DELIVERY_POSTMESSAGE_TOP,
    KEY_DELIVERY_PYAUTOGUI,
    KEY_DELIVERY_SENDINPUT,
    OUTPUT_IMAGES,
    OUTPUT_PDF,
    OUTPUT_TEXT,
    PHASE_ALL,
    PHASE_CAPTURE,
    PHASE_OCR,
    PHASE_PDF,
    PdfTrim,
    Rect,
    WINDOW_CAPTURE_PRINTWINDOW,
    WINDOW_CAPTURE_SCREEN,
    bundled_default_config_path,
)
from core.reader_profiles import (
    apply_reader_profile,
    get_reader_profile,
    list_reader_profiles,
)
from core.windows_util import list_window_titles, window_support_available
from gui.snipping import SnippingWidget
from gui.ui_capture import Ui_Dialog

# CLI --next-key / default_config: pagedown|pageup|right|left|down|up|space|enter
NEXT_KEY_ITEMS = (
    ("Page Down", "pagedown"),
    ("Page Up", "pageup"),
    ("Right", "right"),
    ("Left", "left"),
    ("Down", "down"),
    ("Up", "up"),
    ("Space", "space"),
    ("Enter", "enter"),
)

# CLI --key-delivery
KEY_DELIVERY_ITEMS = (
    ("Auto", KEY_DELIVERY_AUTO),
    ("SendInput", KEY_DELIVERY_SENDINPUT),
    ("PostMessage", KEY_DELIVERY_POSTMESSAGE),
    ("PostMessage (top)", KEY_DELIVERY_POSTMESSAGE_TOP),
    ("PyAutoGUI", KEY_DELIVERY_PYAUTOGUI),
)

# CLI --force-phase
FORCE_PHASE_ITEMS = (
    ("(none)", ""),
    ("capture", PHASE_CAPTURE),
    ("ocr", PHASE_OCR),
    ("pdf", PHASE_PDF),
    ("all", PHASE_ALL),
)

WINDOW_BACKEND_ITEMS = (
    ("PrintWindow", WINDOW_CAPTURE_PRINTWINDOW),
    ("Screen (mss)", WINDOW_CAPTURE_SCREEN),
)

PRESET_MODE_ITEMS = (
    ("Manual — drag region on screen (Region)", CAPTURE_MANUAL),
    ("Active window — full client area", CAPTURE_WINDOW_FULL),
    ("Active window — left 1/3 (full height)", CAPTURE_WINDOW_LEFT_THIRD),
    ("Active window — right 1/3 (full height)", CAPTURE_WINDOW_RIGHT_THIRD),
    ("Screen — left 1/3 (fit window, full height)", CAPTURE_SCREEN_LEFT_THIRD),
)
PRESET_MODES = tuple(mode for _label, mode in PRESET_MODE_ITEMS)

OUTPUT_MODE_ITEMS = (
    ("Images", OUTPUT_IMAGES),
    ("PDF", OUTPUT_PDF),
    ("Text (OCR)", OUTPUT_TEXT),
)

ASSEMBLE_STYLE_ITEMS = (
    ("Full book markdown", "full"),
    ("Prose only (LLM)", "prose"),
    ("Raw OCR (debug)", "raw"),
)

# Extra rows under Options (key delivery / resume / force / backend)
_OPTIONS_EXTRA_H = 100


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


def _default_output_base() -> str:
    base = _repo_root()
    return str(base)


def _combo_index_for_data(combo: QComboBox, value: str, default: int = 0) -> int:
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            return i
    return default


class CaptureDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        self._rect_norm: QRect | None = None
        self._proc: QProcess | None = None
        self._job_config_path: str | None = None
        self._applying_config = False
        # CLI-only / advanced: preserved on load/save, no dedicated widgets
        self._prefer_foreground_window_match = True
        self._debug_capture = False
        self._debug_capture_max_pages = 5
        self._ocr_text_prompt = ""
        self._ocr_prompt_file = ""
        self._input_pdf = ""
        self._fit_on_start = False
        self._start_focus_clicks = 0
        self._start_focus_x_ratio = 0.5
        self._start_focus_y_ratio = 0.5
        self._pdf_trim = PdfTrim()

        self._df_ocr = pd.read_csv(_assets_dir() / "ocr_lang.csv")

        self.ui.cb_ocr_lang_pri.clear()
        self.ui.cb_ocr_lang_sec.clear()
        for lang in self._df_ocr["lang"]:
            self.ui.cb_ocr_lang_pri.addItem(str(lang))
            self.ui.cb_ocr_lang_sec.addItem(str(lang))

        self.ui.lb_pages.hide()
        self.ui.sb_pages.hide()
        self.ui.btn_window.hide()
        self.ui.cb_win_titles.hide()
        self.ui.cb_ocr_lang_sec.hide()  # CLI has a single --ocr-lang
        self.ui.btn_nextpt.hide()
        self.ui.lb_capture_method.hide()  # replaced by Reader row

        # Expand Options group for CLI-parity controls
        self.ui.gb_options.setGeometry(10, 10, 461, 356 + _OPTIONS_EXTRA_H)
        self.ui.btn_save.setGeometry(10, 310 + _OPTIONS_EXTRA_H, 96, 31)
        self.ui.btn_load.setGeometry(115, 310 + _OPTIONS_EXTRA_H, 96, 31)

        # Reader profile row (Kindle / Aladin / …) — applies reader behavior
        self.lb_reader = QLabel("Reader", self.ui.gb_options)
        self.lb_reader.setGeometry(15, 112, 56, 21)
        self.cb_reader = QComboBox(self.ui.gb_options)
        self.cb_reader.setGeometry(75, 108, 205, 26)
        self.cb_reader.addItem("(custom)", "")
        for _profile in list_reader_profiles():
            self.cb_reader.addItem(_profile.label or _profile.name, _profile.name)
        self.cb_reader.setToolTip(
            "Pick a reader to apply its page-turn key, key delivery, focus clicks, etc."
        )
        self.cb_reader.currentIndexChanged.connect(self._on_reader_changed)

        self.ui.cb_next.clear()
        for label, value in NEXT_KEY_ITEMS:
            self.ui.cb_next.addItem(label, value)
        self.ui.cb_next.setGeometry(75, 150, 160, 26)

        self.lb_key_delivery = QLabel("Key send", self.ui.gb_options)
        self.lb_key_delivery.setGeometry(15, 185, 56, 21)
        self.cb_key_delivery = QComboBox(self.ui.gb_options)
        self.cb_key_delivery.setGeometry(75, 180, 160, 26)
        for label, value in KEY_DELIVERY_ITEMS:
            self.cb_key_delivery.addItem(label, value)

        self.lb_focus_clicks = QLabel("Focus clicks", self.ui.gb_options)
        self.lb_focus_clicks.setGeometry(250, 185, 80, 21)
        self.sb_focus_clicks = QSpinBox(self.ui.gb_options)
        self.sb_focus_clicks.setGeometry(335, 180, 111, 26)
        self.sb_focus_clicks.setRange(0, 5)
        self.sb_focus_clicks.setValue(2)
        self.sb_focus_clicks.setToolTip(
            "Clicks near capture top-left before next_key (0 = none)"
        )

        self.cb_output_mode = QComboBox(self.ui.gb_options)
        self.cb_output_mode.setGeometry(75, 215, 371, 26)
        for label, value in OUTPUT_MODE_ITEMS:
            self.cb_output_mode.addItem(label, value)
        self.cb_output_mode.currentIndexChanged.connect(self._on_output_mode_changed)
        self.ui.lb_output.setGeometry(15, 220, 46, 21)

        self.lb_ocr_lang = QLabel("OCR Lang", self.ui.gb_options)
        self.lb_ocr_lang.setGeometry(15, 255, 90, 21)
        self.ui.cb_ocr_lang_pri.setGeometry(75, 250, 160, 26)

        self.lb_assemble_style = QLabel("Markdown", self.ui.gb_options)
        self.lb_assemble_style.setGeometry(15, 290, 56, 21)
        self.cb_assemble_style = QComboBox(self.ui.gb_options)
        self.cb_assemble_style.setGeometry(75, 285, 371, 26)
        for label, value in ASSEMBLE_STYLE_ITEMS:
            self.cb_assemble_style.addItem(label, value)

        self.chk_resume = QCheckBox("Resume (skip done pages)", self.ui.gb_options)
        self.chk_resume.setGeometry(15, 320, 200, 22)
        self.chk_resume.setChecked(True)
        self.chk_resume.setToolTip("Matches CLI --resume / --no-resume")

        self.lb_force_phase = QLabel("Force", self.ui.gb_options)
        self.lb_force_phase.setGeometry(230, 322, 40, 21)
        self.cb_force_phase = QComboBox(self.ui.gb_options)
        self.cb_force_phase.setGeometry(275, 318, 171, 26)
        for label, value in FORCE_PHASE_ITEMS:
            self.cb_force_phase.addItem(label, value)
        self.cb_force_phase.setToolTip("Matches CLI --force-phase")

        self.lb_win_backend = QLabel("Backend", self.ui.gb_options)
        self.lb_win_backend.setGeometry(15, 355, 56, 21)
        self.cb_window_backend = QComboBox(self.ui.gb_options)
        self.cb_window_backend.setGeometry(75, 350, 160, 26)
        for label, value in WINDOW_BACKEND_ITEMS:
            self.cb_window_backend.addItem(label, value)

        self.chk_client_rect = QCheckBox("Client area only", self.ui.gb_options)
        self.chk_client_rect.setGeometry(250, 352, 120, 22)
        self.chk_client_rect.setChecked(True)
        self.chk_client_rect.setToolTip(
            "On = client area; off = full frame (CLI --window-frame)"
        )

        self.chk_hide_cursor = QCheckBox("Hide cursor", self.ui.gb_options)
        self.chk_hide_cursor.setGeometry(375, 352, 80, 22)
        self.chk_hide_cursor.setToolTip("CLI --hide-cursor-during-capture")

        # Capture target group sits below expanded Options
        target_y = 20 + 356 + _OPTIONS_EXTRA_H
        self.gb_capture_target = QGroupBox("Target window & capture area", self)
        self.gb_capture_target.setGeometry(10, target_y, 461, 100)

        self.cb_region_preset = QComboBox(self.gb_capture_target)
        self.cb_region_preset.setGeometry(10, 20, 441, 26)
        for label, _mode in PRESET_MODE_ITEMS:
            self.cb_region_preset.addItem(label)

        self.btn_refresh_windows = QPushButton("Refresh windows", self.gb_capture_target)
        self.btn_refresh_windows.setGeometry(10, 52, 118, 28)

        self.cb_target_window = QComboBox(self.gb_capture_target)
        self.cb_target_window.setEditable(False)
        self.cb_target_window.setGeometry(132, 52, 319, 26)

        lbl_sp = QLabel("Start page #", self.gb_capture_target)
        lbl_sp.setGeometry(10, 86, 72, 21)
        self.sb_start_page = QSpinBox(self.gb_capture_target)
        self.sb_start_page.setGeometry(84, 82, 80, 26)
        self.sb_start_page.setMinimum(1)
        self.sb_start_page.setMaximum(999999)

        lbl_pc = QLabel("Page count", self.gb_capture_target)
        lbl_pc.setGeometry(185, 86, 72, 21)
        self.sb_page_count = QSpinBox(self.gb_capture_target)
        self.sb_page_count.setGeometry(258, 82, 80, 26)
        self.sb_page_count.setMinimum(1)
        self.sb_page_count.setMaximum(10000)

        progress_y = target_y + 110
        self.ui.gb_progress.setGeometry(10, progress_y, 461, 520)

        self.btn_refresh_windows.clicked.connect(self._refresh_window_list)
        self.cb_region_preset.currentIndexChanged.connect(self._on_preset_changed)

        self.ui.sb_delay.setDecimals(2)
        self.ui.sb_delay.setRange(0.05, 120.0)
        self.ui.sb_delay.setSingleStep(0.05)
        self.ui.le_title.setPlaceholderText(
            f"Book title — default: {DEFAULT_BOOK_TITLE}"
        )

        self.btn_assemble = QPushButton("Assemble MD", self.ui.gb_progress)
        self.btn_assemble.setGeometry(170, 115, 118, 31)
        self.ui.btn_start.setGeometry(295, 115, 71, 31)
        self.ui.btn_cancle.setGeometry(375, 115, 76, 31)

        self._refresh_window_list(quiet=True)
        self._apply_defaults()
        self._on_preset_changed()
        self._on_output_mode_changed()

        self.ui.btn_region.clicked.connect(self._pick_region)
        self.ui.btn_browse.clicked.connect(self._browse_folder)
        self.ui.btn_save.clicked.connect(self._save_options)
        self.ui.btn_load.clicked.connect(self._load_options)
        self.ui.btn_start.clicked.connect(self._start_capture)
        self.btn_assemble.clicked.connect(self._start_assemble)
        self.ui.btn_cancle.clicked.connect(self._cancel_job)

        self.setWindowTitle("Ebook Capture")
        self.resize(480, progress_y + 540)

    def _refresh_window_list(self, quiet: bool = False) -> None:
        self.cb_target_window.blockSignals(True)
        self.cb_target_window.clear()
        if not window_support_available():
            self.cb_target_window.addItem("(Windows + pygetwindow required)")
            self.cb_target_window.blockSignals(False)
            return
        titles = list_window_titles()
        for t in titles:
            self.cb_target_window.addItem(t)
        self.cb_target_window.blockSignals(False)
        if not quiet:
            self.ui.pte_status.appendPlainText(
                f"Window list refreshed ({len(titles)} titles).\n"
            )

    def _on_preset_changed(self, *_args: object) -> None:
        manual = self.cb_region_preset.currentIndex() == 0
        self.ui.btn_region.setEnabled(manual)
        win_ok = window_support_available()
        self.btn_refresh_windows.setEnabled(win_ok and not manual)
        self.cb_target_window.setEnabled(win_ok and not manual)

    def _on_output_mode_changed(self, *_args: object) -> None:
        mode = self.cb_output_mode.currentData()
        needs_ocr = mode == OUTPUT_TEXT
        self.lb_ocr_lang.setVisible(needs_ocr)
        self.ui.cb_ocr_lang_pri.setVisible(needs_ocr)

    def _on_reader_changed(self, *_args: object) -> None:
        if self._applying_config:
            return
        name = str(self.cb_reader.currentData() or "")
        if not name:
            return
        cfg = self._config_from_widgets()
        try:
            notes = apply_reader_profile(cfg, name)
        except ValueError as exc:
            QMessageBox.warning(self, "Reader", str(exc))
            return
        self._applying_config = True
        try:
            self._apply_config_to_widgets(cfg)
        finally:
            self._applying_config = False
        self.ui.pte_status.appendPlainText(
            f"Reader profile '{name}': {', '.join(notes)}\n"
        )
        profile = get_reader_profile(name)
        if profile and profile.note:
            self.ui.pte_status.appendPlainText(f"  ↳ {profile.note}\n")

    def _apply_defaults(self) -> None:
        """Load bundled ``default_config.json`` when present; else built-in fallbacks."""
        path = bundled_default_config_path()
        if path.is_file():
            try:
                cfg = CaptureConfig.from_json_file(path)
                self._apply_config_to_widgets(cfg)
                self.ui.pb_progress.setValue(0)
                self.ui.lb_time.setText("Ready")
                self.ui.pte_status.clear()
                self.ui.pte_status.appendPlainText(
                    f"Loaded defaults from package: {path.name}\n\n"
                    "• Manual: Region → drag rectangle.\n"
                    "• Window / screen_left_third: Refresh → pick app → Start.\n"
                    "• Key send / Resume / Force match CLI options.\n"
                    "• After OCR: Assemble MD builds {title}.md from tmp/*.ocr.json.\n"
                )
                return
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        self._apply_hardcoded_defaults()

    def _apply_hardcoded_defaults(self) -> None:
        """Fallback when ``default_config.json`` is missing or invalid."""
        for i in range(len(self._df_ocr)):
            if str(self._df_ocr.iloc[i]["code"]) == "eng":
                self.ui.cb_ocr_lang_pri.setCurrentIndex(i)
                self.ui.cb_ocr_lang_sec.setCurrentIndex(i)
                break

        self.ui.le_folder.setText(_default_output_base())
        self.ui.le_title.clear()
        self._set_output_mode(OUTPUT_PDF)
        self._set_assemble_style("full")

        self.sb_start_page.setValue(1)
        self.sb_page_count.setValue(1)
        self.cb_region_preset.setCurrentIndex(0)

        self.ui.sb_delay.setValue(1.0)
        self.ui.cb_next.setCurrentIndex(0)
        self.cb_key_delivery.setCurrentIndex(
            _combo_index_for_data(self.cb_key_delivery, KEY_DELIVERY_AUTO)
        )
        self.sb_focus_clicks.setValue(2)
        self.chk_resume.setChecked(True)
        self.cb_force_phase.setCurrentIndex(0)
        self.cb_window_backend.setCurrentIndex(
            _combo_index_for_data(self.cb_window_backend, WINDOW_CAPTURE_PRINTWINDOW)
        )
        self.chk_client_rect.setChecked(True)
        self.chk_hide_cursor.setChecked(False)
        self.cb_reader.blockSignals(True)
        self.cb_reader.setCurrentIndex(0)
        self.cb_reader.blockSignals(False)
        self._prefer_foreground_window_match = True
        self._debug_capture = False
        self._debug_capture_max_pages = 5
        self._ocr_text_prompt = ""
        self._ocr_prompt_file = ""
        self._input_pdf = ""
        self._fit_on_start = False
        self._start_focus_clicks = 0
        self._start_focus_x_ratio = 0.5
        self._start_focus_y_ratio = 0.5
        self._pdf_trim = PdfTrim()

        self.ui.pb_progress.setValue(0)
        self.ui.lb_time.setText("Ready")

        self.ui.pte_status.clear()
        self.ui.pte_status.appendPlainText(
            "• Manual: Region → drag. • Window / screen_left_third: Refresh → pick.\n"
            "• Start page # / Page count, then Start.\n"
        )

    def _apply_config_to_widgets(self, cfg: CaptureConfig) -> None:
        """Apply ``CaptureConfig`` to widgets (bundled defaults, Load options, etc.)."""
        base = cfg.base_dir.strip()
        if not base:
            base = _default_output_base()

        self.ui.le_title.setText(cfg.title)
        self.sb_start_page.setValue(max(1, min(cfg.start_page, 999999)))
        self.sb_page_count.setValue(max(1, min(cfg.n_pages, 10000)))
        self.ui.le_folder.setText(base)

        self.cb_reader.blockSignals(True)
        self.cb_reader.setCurrentIndex(
            _combo_index_for_data(self.cb_reader, cfg.reader_profile or "")
        )
        self.cb_reader.blockSignals(False)

        try:
            pi = PRESET_MODES.index(cfg.capture_mode)
        except ValueError:
            pi = 0
        self.cb_region_preset.blockSignals(True)
        self.cb_region_preset.setCurrentIndex(pi)
        self.cb_region_preset.blockSignals(False)

        self.chk_client_rect.setChecked(bool(cfg.use_window_client_rect))
        self._prefer_foreground_window_match = cfg.prefer_foreground_window_match
        self._debug_capture = cfg.debug_capture
        self._debug_capture_max_pages = max(1, int(cfg.debug_capture_max_pages))
        self.cb_window_backend.setCurrentIndex(
            _combo_index_for_data(
                self.cb_window_backend,
                cfg.window_capture_backend,
                default=_combo_index_for_data(
                    self.cb_window_backend, WINDOW_CAPTURE_PRINTWINDOW
                ),
            )
        )
        self.chk_hide_cursor.setChecked(bool(cfg.hide_cursor_during_capture))
        self._ocr_text_prompt = cfg.ocr_text_prompt
        self._ocr_prompt_file = cfg.ocr_prompt_file
        self._input_pdf = cfg.input_pdf or ""
        self._fit_on_start = bool(cfg.fit_on_start)
        self._start_focus_clicks = max(0, min(int(cfg.start_focus_clicks), 5))
        self._start_focus_x_ratio = float(cfg.start_focus_x_ratio)
        self._start_focus_y_ratio = float(cfg.start_focus_y_ratio)
        self._pdf_trim = cfg.pdf_trim

        tw = (cfg.target_window_title or "").strip()
        if tw:
            ix = self.cb_target_window.findText(tw)
            if ix >= 0:
                self.cb_target_window.setCurrentIndex(ix)
            else:
                self.cb_target_window.insertItem(0, tw)
                self.cb_target_window.setCurrentIndex(0)

        self._on_preset_changed()
        self.ui.sb_delay.setValue(float(cfg.delay_sec))
        self.ui.cb_next.setCurrentIndex(
            _combo_index_for_data(self.ui.cb_next, cfg.next_key.lower().strip())
        )
        self.cb_key_delivery.setCurrentIndex(
            _combo_index_for_data(self.cb_key_delivery, cfg.key_delivery)
        )
        self.sb_focus_clicks.setValue(max(0, min(int(cfg.reader_focus_clicks), 5)))
        self.chk_resume.setChecked(bool(cfg.resume))
        self.cb_force_phase.setCurrentIndex(
            _combo_index_for_data(self.cb_force_phase, cfg.force_phase or "")
        )
        self._set_output_mode(cfg.output_mode)
        self._set_assemble_style(cfg.assemble_style)

        pri_code = cfg.ocr_lang
        found_pri = False
        for i in range(len(self._df_ocr)):
            if str(self._df_ocr.iloc[i]["code"]) == pri_code:
                self.ui.cb_ocr_lang_pri.setCurrentIndex(i)
                found_pri = True
                break
        if not found_pri:
            for i in range(len(self._df_ocr)):
                if str(self._df_ocr.iloc[i]["code"]) == "eng":
                    self.ui.cb_ocr_lang_pri.setCurrentIndex(i)
                    break

        r = cfg.rect
        if r.width >= 2 and r.height >= 2:
            self._rect_norm = QRect(r.left, r.top, r.width, r.height)
        else:
            self._rect_norm = None

    def _set_output_mode(self, mode: str) -> None:
        for i in range(self.cb_output_mode.count()):
            if self.cb_output_mode.itemData(i) == mode:
                self.cb_output_mode.setCurrentIndex(i)
                self._on_output_mode_changed()
                return
        self.cb_output_mode.setCurrentIndex(1)
        self._on_output_mode_changed()

    def _set_assemble_style(self, style: str) -> None:
        style = (style or "full").strip().lower()
        for i in range(self.cb_assemble_style.count()):
            if self.cb_assemble_style.itemData(i) == style:
                self.cb_assemble_style.setCurrentIndex(i)
                return
        self.cb_assemble_style.setCurrentIndex(0)

    def _pick_region(self) -> None:
        loop = QEventLoop()
        snip = SnippingWidget()
        snip.regionSelected.connect(loop.quit)
        snip.regionCancelled.connect(loop.quit)
        snip.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        snip.show()
        snip.raise_()
        snip.activateWindow()
        snip.setFocus(Qt.PopupFocusReason)
        loop.exec_()

        if snip.was_aborted() or not snip.was_completed():
            self.ui.pte_status.appendPlainText("Region selection cancelled.\n")
            return

        rect = snip.getRect()
        if rect.width() < 2 or rect.height() < 2:
            QMessageBox.warning(
                self,
                "Region",
                "Selection too small. Drag a larger rectangle.",
            )
            return

        self._rect_norm = rect
        self.ui.pte_status.appendPlainText(
            f"Region: {rect.x()},{rect.y()} {rect.width()}×{rect.height()}\n"
        )

    def _browse_folder(self) -> None:
        start = self.ui.le_folder.text().strip() or _default_output_base()
        path = QFileDialog.getExistingDirectory(
            self,
            "Select output folder (parent for each book)",
            start,
        )
        if path:
            self.ui.le_folder.setText(path)

    def _save_options(self) -> None:
        cfg = self._config_from_widgets()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save options",
            str(Path.home() / "ebook_capture_options.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        cfg.to_json_file(path)
        self.ui.pte_status.appendPlainText(f"Saved options: {path}\n")

    def _load_options(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load options",
            str(Path.home()),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            cfg = CaptureConfig.from_json_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as e:
            QMessageBox.warning(self, "Load", f"Could not load file:\n{e}")
            return

        self._apply_config_to_widgets(cfg)
        r = cfg.rect
        if r.width >= 2 and r.height >= 2:
            self.ui.pte_status.appendPlainText(
                f"Loaded region {r.left},{r.top} {r.width}×{r.height}\n"
            )
        else:
            self.ui.pte_status.appendPlainText(
                "No valid region in file — pick Region again.\n"
            )
        self.ui.pte_status.appendPlainText(f"Loaded options: {path}\n")

    def _config_from_widgets(self) -> CaptureConfig:
        pi = self.cb_region_preset.currentIndex()
        capture_mode = PRESET_MODES[max(0, min(pi, len(PRESET_MODES) - 1))]

        rect = Rect(0, 0, 0, 0)
        if capture_mode == CAPTURE_MANUAL and self._rect_norm is not None:
            rect = Rect(
                left=self._rect_norm.left(),
                top=self._rect_norm.top(),
                width=self._rect_norm.width(),
                height=self._rect_norm.height(),
            )

        next_key = str(self.ui.cb_next.currentData() or "pagedown")
        pri = self.ui.cb_ocr_lang_pri.currentText()
        ocr_lang = self._ocr_code(pri) if pri else "eng"

        tw = self.cb_target_window.currentText().strip()
        if tw.startswith("("):
            tw = ""

        output_mode = str(self.cb_output_mode.currentData() or OUTPUT_PDF)
        cfg = CaptureConfig(
            title=self.ui.le_title.text().strip() or DEFAULT_BOOK_TITLE,
            n_pages=int(self.sb_page_count.value()),
            start_page=int(self.sb_start_page.value()),
            base_dir=str(
                Path(self.ui.le_folder.text().strip() or _default_output_base()).expanduser()
            ),
            rect=rect,
            capture_mode=capture_mode,
            target_window_title=tw,
            use_window_client_rect=self.chk_client_rect.isChecked(),
            prefer_foreground_window_match=self._prefer_foreground_window_match,
            debug_capture=self._debug_capture,
            debug_capture_max_pages=self._debug_capture_max_pages,
            window_capture_backend=str(
                self.cb_window_backend.currentData() or WINDOW_CAPTURE_PRINTWINDOW
            ),
            hide_cursor_during_capture=self.chk_hide_cursor.isChecked(),
            delay_sec=float(self.ui.sb_delay.value()),
            next_key=next_key,
            reader_focus_clicks=int(self.sb_focus_clicks.value()),
            key_delivery=str(self.cb_key_delivery.currentData() or KEY_DELIVERY_AUTO),
            output_mode=output_mode,
            resume=self.chk_resume.isChecked(),
            force_phase=str(self.cb_force_phase.currentData() or ""),
            ocr_lang=ocr_lang,
            ocr_text_prompt=self._ocr_text_prompt,
            ocr_prompt_file=self._ocr_prompt_file,
            assemble_style=str(self.cb_assemble_style.currentData() or "full"),
            input_pdf=self._input_pdf,
            reader_profile=str(self.cb_reader.currentData() or ""),
            fit_on_start=bool(self._fit_on_start),
            start_focus_clicks=int(self._start_focus_clicks),
            start_focus_x_ratio=float(self._start_focus_x_ratio),
            start_focus_y_ratio=float(self._start_focus_y_ratio),
            pdf_trim=self._pdf_trim,
        )
        cfg.normalize()
        return cfg

    def _ocr_code(self, combo_text: str) -> str:
        row = self._df_ocr.loc[self._df_ocr["lang"] == combo_text]
        return str(row["code"].iloc[0])

    def _build_config(self) -> CaptureConfig | None:
        pi = self.cb_region_preset.currentIndex()
        mode = PRESET_MODES[max(0, min(pi, len(PRESET_MODES) - 1))]

        if mode == CAPTURE_MANUAL:
            if (
                self._rect_norm is None
                or self._rect_norm.width() < 2
                or self._rect_norm.height() < 2
            ):
                QMessageBox.warning(
                    self,
                    "Region",
                    "Manual mode: tap Region and drag a rectangle on the screen.",
                )
                return None
        else:
            if not window_support_available():
                QMessageBox.warning(
                    self,
                    "Window capture",
                    "Window-based capture needs Windows with pygetwindow installed.",
                )
                return None
            wt = self.cb_target_window.currentText().strip()
            if not wt or wt.startswith("("):
                QMessageBox.warning(
                    self,
                    "Window",
                    "Select an application window from the list (Refresh windows first).",
                )
                return None

        title = self.ui.le_title.text().strip() or DEFAULT_BOOK_TITLE
        base = self.ui.le_folder.text().strip()
        if not Path(base).expanduser().is_absolute():
            QMessageBox.warning(
                self,
                "Folder",
                "Use an absolute output folder (Browse… or full path).",
            )
            return None
        n_pages = int(self.sb_page_count.value())
        if n_pages < 1:
            QMessageBox.warning(self, "Pages", "Page count must be at least 1.")
            return None

        cfg = self._config_from_widgets()
        cfg.title = title
        cfg.n_pages = n_pages
        cfg.start_page = int(self.sb_start_page.value())
        cfg.base_dir = str(Path(base).expanduser())
        if mode == CAPTURE_MANUAL:
            cfg.rect = Rect(
                left=self._rect_norm.left(),
                top=self._rect_norm.top(),
                width=self._rect_norm.width(),
                height=self._rect_norm.height(),
            )
        return cfg

    def _assemble_preflight(self, cfg: CaptureConfig) -> str | None:
        base = Path(cfg.base_dir).expanduser()
        if not base.is_absolute():
            return "Use an absolute output folder (Browse… or full path)."
        tmp = cfg.tmp_dir()
        if not tmp.is_dir():
            return f"OCR folder not found:\n{tmp}"
        pattern = f"{cfg.title}_*.ocr.json"
        if not any(tmp.glob(pattern)):
            return f"No OCR JSON matching {pattern} in:\n{tmp}"
        return None

    def _python_env(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        root = str(_repo_root())
        prev = env.value("PYTHONPATH", "")
        merged = root if not prev else root + os.pathsep + prev
        env.insert("PYTHONPATH", merged)
        return env

    def _job_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def _start_subprocess(self, arguments: list[str], *, label: str) -> None:
        if self._job_running():
            QMessageBox.information(self, "Busy", "A job is already running.")
            return

        self._proc = QProcess(self)
        self._proc.setProcessEnvironment(self._python_env())
        self._proc.setProgram(sys.executable)
        self._proc.setArguments(arguments)
        self._proc.readyReadStandardOutput.connect(self._read_stdout)
        self._proc.readyReadStandardError.connect(self._read_stderr)
        self._proc.finished.connect(self._on_finished)

        self.ui.pb_progress.setRange(0, 0)
        self.ui.lb_time.setText("Running…")
        self.ui.pte_status.appendPlainText(f"Starting {label}…\n")
        self._proc.start()

    def _start_capture(self) -> None:
        if self._job_running():
            QMessageBox.information(self, "Busy", "A capture job is already running.")
            return
        cfg = self._build_config()
        if cfg is None:
            return
        try:
            cfg.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Options", str(e))
            return

        fd, path = tempfile.mkstemp(suffix=".json", prefix="ebook_capture_")
        os.close(fd)
        cfg.to_json_file(path)
        self._job_config_path = path
        self._start_subprocess(
            ["-m", "ebook_capture", "run", "-y", "--config", path],
            label="run subprocess",
        )

    def _start_assemble(self) -> None:
        cfg = self._config_from_widgets()
        cfg.output_mode = OUTPUT_TEXT
        err = self._assemble_preflight(cfg)
        if err:
            QMessageBox.warning(self, "Assemble", err)
            return

        fd, path = tempfile.mkstemp(suffix=".json", prefix="ebook_assemble_")
        os.close(fd)
        cfg.to_json_file(path)
        self._job_config_path = path
        style = str(self.cb_assemble_style.currentData() or cfg.assemble_style or "full")
        self._start_subprocess(
            [
                "-m",
                "ebook_capture",
                "run",
                "-y",
                "--config",
                path,
                "--style",
                style,
            ],
            label=f"assemble ({style})",
        )

    def _read_stdout(self) -> None:
        if self._proc:
            text = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
            if text.strip():
                self.ui.pte_status.appendPlainText(text.rstrip() + "\n")
                for line in text.splitlines():
                    if line.startswith("IMAGE_OK"):
                        self.ui.pb_progress.setMaximum(100)
                        self.ui.pb_progress.setValue(min(99, self.ui.pb_progress.value() + 1))

    def _read_stderr(self) -> None:
        if self._proc:
            text = bytes(self._proc.readAllStandardError()).decode("utf-8", errors="replace")
            if text.strip():
                self.ui.pte_status.appendPlainText("[stderr] " + text.rstrip() + "\n")

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self.ui.pb_progress.setMaximum(100)
        self.ui.pb_progress.setValue(100 if code == 0 else 0)
        self.ui.lb_time.setText("Done" if code == 0 else f"Exit {code}")
        self.ui.pte_status.appendPlainText(f"Process exited with code {code}\n")
        if self._job_config_path and Path(self._job_config_path).exists():
            try:
                Path(self._job_config_path).unlink(missing_ok=True)
            except OSError:
                pass
        self._job_config_path = None

    def _cancel_job(self) -> None:
        if self._job_running():
            self._proc.kill()
            self.ui.pte_status.appendPlainText("Cancelled.\n")
            self.ui.lb_time.setText("Cancelled")


def run_gui() -> None:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    from gui.theme import apply_material_theme

    apply_material_theme(app, dark=True)

    dlg = CaptureDialog()
    dlg.resize(max(520, dlg.width()), dlg.height())
    dlg.show()

    sys.exit(app.exec_())
