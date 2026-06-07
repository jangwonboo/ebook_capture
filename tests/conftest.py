"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SAMPLE_BOOK_TMP = TESTS_DIR / "fixtures" / "sample_book" / "tmp"


@pytest.fixture
def sample_book_tmp() -> Path:
    return SAMPLE_BOOK_TMP


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
