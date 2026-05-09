"""Compatibility wrapper for ``python -m ebook_capture`` from the repo root."""

from cli import main


if __name__ == "__main__":
    raise SystemExit(main())
