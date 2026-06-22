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
    OUTPUT_IMAGES,
    OUTPUT_PDF,
    OUTPUT_TEXT,
    Rect,
    WINDOW_CAPTURE_PRINTWINDOW,
    bundled_default_config_path,
)
from core.windows_util import list_window_titles, window_support_available
from gui.snipping import SnippingWidget
from gui.ui_capture import Ui_Dialog

# Maps capture.ui combo order → pyautogui key names (must match cb_next item order)
NEXT_KEY_BY_INDEX = (
    "pagedown",
    "pagedown",
    "down",
    "right",
    "space",
    "enter",
)

PRESET_MODES = (
    CAPTURE_MANUAL,
    CAPTURE_WINDOW_FULL,
    CAPTURE_WINDOW_LEFT_THIRD,
    CAPTURE_WINDOW_RIGHT_THIRD,
    CAPTURE_SCREEN_LEFT_THIRD,
)

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

_CAPTURE_UI_SHIFT = 118


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


def _default_output_base() -> str:
    base = _repo_root()
    return str(base)


def _next_key_to_index(key: str) -> int:
    key_l = key.lower().strip()
    for i, k in enumerate(NEXT_KEY_BY_INDEX):
        if k == key_l:
            return i
    return 0


class CaptureDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        self._rect_norm: QRect | None = None
        self._proc: QProcess | None = None
        self._job_config_path: str | None = None
        self._use_window_client_rect = True
        self._prefer_foreground_window_match = True
        self._debug_capture = False
        self._debug_capture_max_pages = 5
        self._window_capture_backend = WINDOW_CAPTURE_PRINTWINDOW
        self._hide_cursor_during_capture = False
        self._ocr_text_prompt = ""
        self._ocr_prompt_file = ""

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

        self.gb_capture_target = QGroupBox("Target window & capture area", self)
        self.gb_capture_target.setGeometry(
            10, 376, 461, _CAPTURE_UI_SHIFT - 18
        )

        self.cb_region_preset = QComboBox(self.gb_capture_target)
        self.cb_region_preset.setGeometry(10, 20, 441, 26)
        self.cb_region_preset.addItems(
            [
                "Manual — drag region on screen (Region)",
                "Active window — full client area",
                "Active window — left 1/3 (full height)",
                "Active window — right 1/3 (full height)",
            ]
        )

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

        self.ui.gb_progress.setGeometry(
            10,
            370 + _CAPTURE_UI_SHIFT,
            461,
            max(520, 656 - _CAPTURE_UI_SHIFT),
        )

        self.btn_refresh_windows.clicked.connect(self._refresh_window_list)
        self.cb_region_preset.currentIndexChanged.connect(self._on_preset_changed)

        self.ui.sb_delay.setDecimals(2)
        self.ui.sb_delay.setRange(0.05, 120.0)
        self.ui.sb_delay.setSingleStep(0.05)
        self.ui.le_title.setPlaceholderText(
            f"Book title — default: {DEFAULT_BOOK_TITLE}"
        )

        self.cb_output_mode = QComboBox(self.ui.gb_options)
        self.cb_output_mode.setGeometry(75, 195, 371, 26)
        for label, value in OUTPUT_MODE_ITEMS:
            self.cb_output_mode.addItem(label, value)
        self.cb_output_mode.currentIndexChanged.connect(self._on_output_mode_changed)

        self.lb_ocr_lang = QLabel("OCR Lang", self.ui.gb_options)
        self.lb_ocr_lang.setGeometry(75, 230, 90, 21)
        self.ui.cb_ocr_lang_pri.setGeometry(235, 230, 101, 26)
        self.ui.cb_ocr_lang_sec.setGeometry(345, 230, 101, 26)

        self.lb_assemble_style = QLabel("Markdown", self.ui.gb_options)
        self.lb_assemble_style.setGeometry(15, 265, 56, 21)
        self.cb_assemble_style = QComboBox(self.ui.gb_options)
        self.cb_assemble_style.setGeometry(75, 260, 371, 26)
        for label, value in ASSEMBLE_STYLE_ITEMS:
            self.cb_assemble_style.addItem(label, value)

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
        self.resize(480, 1034 + _CAPTURE_UI_SHIFT)

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
        self.ui.cb_ocr_lang_sec.setVisible(needs_ocr)

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
                    "• Window: Refresh windows → pick app → full or left/right third.\n"
                    "• Set Start page # and Page count, then Start.\n"
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
        self.ui.pb_progress.setValue(0)
        self.ui.lb_time.setText("Ready")

        self.ui.pte_status.clear()
        self.ui.pte_status.appendPlainText(
            "• Manual: Region → drag. • Window: Refresh → pick window.\n"
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

        try:
            pi = PRESET_MODES.index(cfg.capture_mode)
        except ValueError:
            pi = 0
        self.cb_region_preset.blockSignals(True)
        self.cb_region_preset.setCurrentIndex(pi)
        self.cb_region_preset.blockSignals(False)

        self._use_window_client_rect = cfg.use_window_client_rect
        self._prefer_foreground_window_match = cfg.prefer_foreground_window_match
        self._debug_capture = cfg.debug_capture
        self._debug_capture_max_pages = max(1, int(cfg.debug_capture_max_pages))
        self._window_capture_backend = cfg.window_capture_backend
        self._hide_cursor_during_capture = cfg.hide_cursor_during_capture
        self._ocr_text_prompt = cfg.ocr_text_prompt
        self._ocr_prompt_file = cfg.ocr_prompt_file

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
        self.ui.cb_next.setCurrentIndex(_next_key_to_index(cfg.next_key))
        self._set_output_mode(cfg.output_mode)
        self._set_assemble_style(cfg.assemble_style)

        pri_code = cfg.ocr_lang
        found_pri = False
        for i in range(len(self._df_ocr)):
            if str(self._df_ocr.iloc[i]["code"]) == pri_code:
                self.ui.cb_ocr_lang_pri.setCurrentIndex(i)
                self.ui.cb_ocr_lang_sec.setCurrentIndex(i)
                found_pri = True
                break
        if not found_pri:
            for i in range(len(self._df_ocr)):
                if str(self._df_ocr.iloc[i]["code"]) == "eng":
                    self.ui.cb_ocr_lang_pri.setCurrentIndex(i)
                    self.ui.cb_ocr_lang_sec.setCurrentIndex(i)
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

        idx = self.ui.cb_next.currentIndex()
        next_key = NEXT_KEY_BY_INDEX[max(0, min(idx, len(NEXT_KEY_BY_INDEX) - 1))]
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
            base_dir=str(Path(self.ui.le_folder.text().strip() or _default_output_base()).expanduser()),
            rect=rect,
            capture_mode=capture_mode,
            target_window_title=tw,
            use_window_client_rect=self._use_window_client_rect,
            prefer_foreground_window_match=self._prefer_foreground_window_match,
            debug_capture=self._debug_capture,
            debug_capture_max_pages=self._debug_capture_max_pages,
            window_capture_backend=self._window_capture_backend,
            hide_cursor_during_capture=self._hide_cursor_during_capture,
            delay_sec=float(self.ui.sb_delay.value()),
            next_key=next_key,
            output_mode=output_mode,
            resume=True,
            ocr_lang=ocr_lang,
            ocr_text_prompt=self._ocr_text_prompt,
            ocr_prompt_file=self._ocr_prompt_file,
            assemble_style=str(self.cb_assemble_style.currentData() or "full"),
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
