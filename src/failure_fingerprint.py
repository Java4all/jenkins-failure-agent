"""
Structured failure localization metadata for RC analysis and API consumers.

Used to expose how LogParser vs RootCauseFinder aligned without a full pipeline rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def merge_retriable_with_kb(
    model_retriable: bool,
    kb_retriable: Optional[bool],
    kb_match_confidence: float,
    *,
    high_trust_threshold: float = 0.75,
) -> bool:
    """
    Merge model/pattern retriability with knowledge-base ToolError.retriable.

    - No KB match: use model/pattern only.
    - Strong KB match (confidence >= threshold): KB wins (org runbook / tool policy).
    - Weak KB match: conservative AND — both must be retriable to mark retriable.
    """
    if kb_retriable is None:
        return bool(model_retriable)
    if kb_match_confidence >= high_trust_threshold:
        return bool(kb_retriable)
    return bool(model_retriable) and bool(kb_retriable)


@dataclass
class FailureFingerprint:
    """Primary error line resolution across finder vs parser (1-based line numbers for logs)."""

    finder_primary_line_1based: int = 0
    parser_primary_line_1based: Optional[int] = None
    chosen_primary_line_1based: int = 0
    chosen_source: str = "finder"  # finder|parser_early_scm|parser_precedes_tail|finder_with_note
    aligned: bool = True
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finder_primary_line_1based": self.finder_primary_line_1based,
            "parser_primary_line_1based": self.parser_primary_line_1based,
            "chosen_primary_line_1based": self.chosen_primary_line_1based,
            "chosen_source": self.chosen_source,
            "aligned": self.aligned,
            "note": self.note,
        }


def empty_fingerprint() -> FailureFingerprint:
    return FailureFingerprint()
