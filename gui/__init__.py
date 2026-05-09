"""PyQt5 UI — launches capture jobs via `python -m ebook_capture capture`."""


def run_gui() -> None:
    from gui.app import run_gui as _run_gui

    _run_gui()


__all__ = ["run_gui"]
