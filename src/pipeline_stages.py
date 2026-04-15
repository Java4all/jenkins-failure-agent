"""
Declarative Pipeline stage markers in Jenkins console output.

Typical sequence:
  [Pipeline] stage
  [Pipeline] { (Stage label)    # label may include spaces, parens, braces (varies by Jenkins)

End of block (informational):
  [Pipeline] // stage

Spacing after ``[Pipeline]`` is flexible (\\s*).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Lines often begin with timestamps; match [Pipeline] ... at end of line where needed.
_PIPELINE_STAGE_HEADER = re.compile(r"\[Pipeline\]\s*stage\s*$", re.IGNORECASE)

_PIPELINE_STAGE_END = re.compile(r"\[Pipeline\]\s*//\s*stage\s*$", re.IGNORECASE)

_PIPELINE_ANY = re.compile(r"\[Pipeline\]\s*(.*)$", re.IGNORECASE)

_LEGACY_BRACE_FORM = re.compile(
    r"\[Pipeline\]\s*\{\s*\((.*)\)\s*$",
    re.IGNORECASE,
)


def _from_pipeline(line: str) -> str:
    """Strip optional leading timestamp; return from ``[Pipeline]`` onward."""
    i = line.find("[Pipeline]")
    if i < 0:
        return ""
    return line[i:].rstrip()


def _normalize_stage_label(fragment: str) -> str:
    """
    Turn the text after [Pipeline] on the stage *name* line into a display label.

    Handles forms like:
      { (Build)
      { (Deploy (QA))
      ( Build )
      plain-name
    """
    t = (fragment or "").strip()
    if not t:
        return ""

    # Declarative: { ... ( inner ) ... } — take innermost (...) if wrapped in { }
    if "{" in t and "(" in t:
        rp = t.rfind(")")
        lp = t.find("(")
        if lp != -1 and rp > lp:
            inner = t[lp + 1 : rp].strip()
            if inner:
                return inner

    if t.startswith("(") and t.endswith(")") and len(t) >= 2:
        return t[1:-1].strip()

    return t


def _line_follows_only_blanks_after_stage_header(lines: List[str], i: int) -> bool:
    """
    True if line ``i`` is the Declarative *name* line: the first non-blank line
    above it is ``[Pipeline] stage`` (only blank lines may appear in between).
    Used to avoid treating ``[Pipeline] { (name)`` as *legacy* single-line stage
    when it is actually the second line of the two-line Declarative form.
    """
    j = i - 1
    while j >= 0:
        tail = _from_pipeline(lines[j])
        if not tail.strip():
            j -= 1
            continue
        return bool(_PIPELINE_STAGE_HEADER.search(tail))
    return False


def parse_stage_name_from_pipeline_line(line: str) -> Optional[str]:
    """
    If ``line`` is the stage *name* line (the line after ``[Pipeline] stage``),
    return the normalized stage name; otherwise return None if this line is not
    a valid stage name line (e.g. ``[Pipeline] echo``).
    """
    raw = _from_pipeline(line)
    if not raw:
        return None
    m = _PIPELINE_ANY.match(raw.strip())
    if not m:
        return None
    rest = m.group(1) or ""
    rest_stripped = rest.strip()
    if not rest_stripped:
        return None
    low = rest_stripped.lower()
    # Not a stage label line
    if low == "stage" or rest_stripped.startswith("//"):
        return None
    first_tok = low.split()[0] if low else ""
    if first_tok in ("echo", "sh", "node", "script", "library", "tool", "properties", "parallel", "stage"):
        return None

    legacy = _LEGACY_BRACE_FORM.match(raw.strip())
    if legacy:
        return _normalize_stage_label(legacy.group(1))

    return _normalize_stage_label(rest_stripped) or None


def find_declarative_stages(lines: List[str]) -> Tuple[Optional[str], int, List[str]]:
    """
    Scan full console lines for Declarative ``stage`` blocks.

    Returns:
        (last_stage_name, last_stage_start_line_index, ordered_stage_names)

    ``last_stage_start_line_index`` is the 0-based index of the ``[Pipeline] stage`` line
    that opened the last completed stage name we parsed (best effort).
    """
    sequence: List[str] = []
    last_name: Optional[str] = None
    last_idx = -1

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        tail = _from_pipeline(line)
        if not tail or not _PIPELINE_STAGE_HEADER.search(tail):
            # Single-line legacy: [Pipeline] { (name) (may have leading timestamp)
            if tail:
                legacy = _LEGACY_BRACE_FORM.match(tail.strip())
                if legacy and not _line_follows_only_blanks_after_stage_header(lines, i):
                    name = _normalize_stage_label(legacy.group(1))
                    if name:
                        if not sequence or sequence[-1] != name:
                            sequence.append(name)
                        last_name = name
                        last_idx = i
            i += 1
            continue

        # [Pipeline] stage — next meaningful [Pipeline] line should be the label
        name: Optional[str] = None
        for j in range(i + 1, min(i + 8, n)):
            candidate_line = lines[j]
            ct = _from_pipeline(candidate_line)
            if not ct.strip():
                continue
            if _PIPELINE_STAGE_END.search(ct):
                break
            if _PIPELINE_STAGE_HEADER.search(ct):
                break
            parsed = parse_stage_name_from_pipeline_line(candidate_line)
            if parsed:
                name = parsed
                break

        if name:
            sequence.append(name)
            last_name = name
            last_idx = i
        i += 1

    return last_name, last_idx, sequence
