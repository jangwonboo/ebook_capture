"""Ebook screen capture: CLI pipeline + optional PyQt GUI."""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.2.0"

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import main

__all__ = ["__version__", "main"]
