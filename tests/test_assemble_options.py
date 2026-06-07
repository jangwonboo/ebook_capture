"""Tests for Markdown assemble style presets."""

from __future__ import annotations

import unittest

from core.assemble_options import AssembleOptions, AssembleStyle


class AssembleOptionsTests(unittest.TestCase):
    def test_full_defaults(self) -> None:
        opts = AssembleOptions()
        self.assertEqual(opts.style, AssembleStyle.FULL)
        self.assertTrue(opts.fix_text)
        self.assertFalse(opts.body_only)

    def test_prose(self) -> None:
        opts = AssembleOptions(style=AssembleStyle.PROSE)
        self.assertTrue(opts.body_only)
        self.assertFalse(opts.include_page_comments())


if __name__ == "__main__":
    unittest.main()
