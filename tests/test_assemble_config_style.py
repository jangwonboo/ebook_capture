"""assemble reads assemble_style from config when --style omitted."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cli import _cmd_run

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sample_book" / "tmp"


class AssembleConfigStyleTests(unittest.TestCase):
    def test_config_default_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book_dir = root / "SampleBook" / "tmp"
            book_dir.mkdir(parents=True)
            for src in FIXTURES.glob("SampleBook_*.ocr.json"):
                (book_dir / src.name).write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8"
                )

            config_path = root / "cfg.json"
            config_path.write_text(
                json.dumps(
                    {
                        "title": "SampleBook",
                        "base_dir": str(root),
                        "output_mode": "text",
                        "assemble_style": "prose",
                    }
                ),
                encoding="utf-8",
            )

            class Args:
                config = config_path
                title = None
                base_dir = None
                style = None
                yes = True
                active_window = False

            rc = _cmd_run(Args())
            self.assertEqual(rc, 0)
            md = (root / "SampleBook" / "SampleBook.md").read_text(encoding="utf-8")
            self.assertNotIn("### ", md)


if __name__ == "__main__":
    unittest.main()
