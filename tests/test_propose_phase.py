"""Tests for PROPOSE phase consensus helpers."""

from conductor.phases.propose import _find_contradiction_consensus


def test_find_contradiction_consensus_same_quote():
    records = [
        (
            "claude",
            {
                "spec_contradictions": [
                    {"quote": "Use SQLite", "why_conflicts": "Spec requires Postgres", "resolution_options": ["A"]},
                ]
            },
        ),
        (
            "codex",
            {
                "spec_contradictions": [
                    {"quote": "Use SQLite", "why_conflicts": "Conflicts with scale requirement", "resolution_options": ["B"]},
                ]
            },
        ),
        ("gemini", {"spec_contradictions": []}),
    ]
    consensus = _find_contradiction_consensus(records, required_count=2)
    assert consensus is not None
    assert len(consensus["models"]) == 2


def test_find_contradiction_consensus_different_quotes():
    records = [
        ("claude", {"spec_contradictions": [{"quote": "A", "why_conflicts": "x", "resolution_options": ["1"]}]}),
        ("codex", {"spec_contradictions": [{"quote": "B", "why_conflicts": "y", "resolution_options": ["1"]}]}),
    ]
    consensus = _find_contradiction_consensus(records, required_count=2)
    assert consensus is None
