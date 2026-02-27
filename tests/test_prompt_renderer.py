"""Tests for conductor.prompt_renderer module."""

from conductor.prompt_renderer import render, render_prompt, load_prompt


def test_render_basic():
    template = "Hello {{NAME}}, you are {{ROLE}}."
    result = render(template, {"NAME": "Alice", "ROLE": "proposer"})
    assert result == "Hello Alice, you are proposer."


def test_render_missing_variable():
    template = "Hello {{NAME}}, {{UNKNOWN}} here."
    result = render(template, {"NAME": "Bob"})
    assert result == "Hello Bob, {{UNKNOWN}} here."


def test_render_no_variables():
    template = "No placeholders here."
    result = render(template, {})
    assert result == "No placeholders here."


def test_load_prompt_proposer():
    text = load_prompt("proposer")
    assert "PROPOSER" in text
    assert "{{TASK}}" in text


def test_load_prompt_builder():
    text = load_prompt("builder")
    assert "BUILDER" in text
    assert "{{MASTER_PLAN_JSON}}" in text


def test_render_prompt():
    result = render_prompt("proposer", {"TASK": "Build a CLI", "CONSTRAINTS": "None", "REPO_SUMMARY": "N/A"})
    assert "Build a CLI" in result
    assert "{{TASK}}" not in result
