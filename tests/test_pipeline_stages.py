"""Tests for Declarative Pipeline stage parsing."""

import pytest

from src.pipeline_stages import find_declarative_stages, parse_stage_name_from_pipeline_line


@pytest.mark.unit
def test_two_line_stage_flexible_spaces():
    lines = [
        "12:00:00  [Pipeline]  stage",
        "12:00:00  [Pipeline]   { (Build & Test)  ",
        "12:00:01  + mvn clean",
    ]
    last, idx, seq = find_declarative_stages(lines)
    assert last == "Build & Test"
    assert idx == 0
    assert "Build & Test" in seq


@pytest.mark.unit
def test_stage_name_with_nested_parens():
    line = "[Pipeline] { (Deploy (QA))  "
    assert parse_stage_name_from_pipeline_line(line) == "Deploy (QA)"


@pytest.mark.unit
def test_two_line_stage_blank_line_between_header_and_name():
    lines = [
        "[Pipeline] stage",
        "",
        "  [Pipeline]  { (Build) ",
    ]
    last, idx, seq = find_declarative_stages(lines)
    assert last == "Build"
    assert idx == 0


@pytest.mark.unit
def test_legacy_single_line_only():
    lines = [
        "[Pipeline] { (Only Legacy)",
    ]
    last, idx, seq = find_declarative_stages(lines)
    assert last == "Only Legacy"
    assert seq


@pytest.mark.unit
def test_rejects_echo_as_stage_name():
    assert parse_stage_name_from_pipeline_line("[Pipeline] echo") is None
