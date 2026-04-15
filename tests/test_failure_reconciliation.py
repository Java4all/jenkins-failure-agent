"""Tests for LogParser vs RootCauseFinder reconciliation and KB helpers."""

import pytest


@pytest.mark.unit
def test_reconcile_prefers_early_scm_over_tail_focus():
    from src.rc_finder import RootCauseFinder

    class MockErr:
        line_number = 3

    class MockParsed:
        errors = [MockErr()]

    lines = ["noop"] * 100
    lines[2] = "fatal: Couldn't find any revision to build"
    lines[90] = "npm ERR! extraneous failure noise"

    finder = RootCauseFinder({})
    idx, line, note, fp = finder._reconcile_primary_error_line(lines, 89, 8, MockParsed())
    assert idx == 2
    assert "revision" in line.lower() or "fatal" in line.lower()
    assert note
    assert fp.chosen_source == "parser_early_scm"
    assert fp.chosen_primary_line_1based == 3
