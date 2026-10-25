"""Assemble-md output presets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssembleStyle(str, Enum):
    FULL = "full"
    PROSE = "prose"
    RAW = "raw"


_STYLE_DEFAULTS: dict[AssembleStyle, tuple[bool, bool, bool]] = {
    AssembleStyle.FULL: (True, False, False),
    AssembleStyle.PROSE: (True, True, False),
    AssembleStyle.RAW: (False, False, True),
}


@dataclass(frozen=True)
class AssembleOptions:
    style: AssembleStyle = AssembleStyle.FULL
    page_comments: bool | None = None
    # OCR typo correction (dictionary + in-book frequency); only with fix_text.
    fix_typos: bool = True
    # In-book frequency heuristic on top of the dictionary (opt-in: many false hits).
    typo_frequency: bool = False
    # Claude proofreading of OCR misreads (paid; cached per page in tmp/*.proof.json).
    llm_proofread: bool = False
    proofread_model: str = "claude-opus-5-5"
    proofread_workers: int = 4

    @property
    def fix_text(self) -> bool:
        return _STYLE_DEFAULTS[self.style][0]

    @property
    def fix_ocr_typos(self) -> bool:
        return self.fix_text and self.fix_typos

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
        fix_typos: bool = True,
        typo_frequency: bool = False,
        llm_proofread: bool = False,
        proofread_model: str | None = None,
        proofread_workers: int = 4,
    ) -> AssembleOptions:
        return cls(
            style=AssembleStyle(style),
            page_comments=page_comments,
            fix_typos=fix_typos,
            typo_frequency=typo_frequency,
            llm_proofread=llm_proofread,
            proofread_model=proofread_model or cls.proofread_model,
            proofread_workers=proofread_workers,
        )
