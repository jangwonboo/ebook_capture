"""Assemble-md output presets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssembleStyle(str, Enum):
    FULL = "full"
    PROSE = "prose"
    RAW = "raw"


_STYLE_DEFAULTS: dict[AssembleStyle, tuple[bool, bool, bool]] = {
    AssembleStyle.FULL: (True, False, True),
    AssembleStyle.PROSE: (True, True, False),
    AssembleStyle.RAW: (False, False, True),
}


@dataclass(frozen=True)
class AssembleOptions:
    style: AssembleStyle = AssembleStyle.FULL
    page_comments: bool | None = None

    @property
    def fix_text(self) -> bool:
        return _STYLE_DEFAULTS[self.style][0]

    @property
    def body_only(self) -> bool:
        return _STYLE_DEFAULTS[self.style][1]

    def include_page_comments(self) -> bool:
        if self.page_comments is not None:
            return self.page_comments
        return _STYLE_DEFAULTS[self.style][2]

    @classmethod
    def from_cli(
        cls,
        *,
        style: str = "full",
        page_comments: bool | None = None,
    ) -> AssembleOptions:
        return cls(style=AssembleStyle(style), page_comments=page_comments)
