"""Tests for PROPOSE phase consensus helpers."""

import conductor.phases.propose as propose_phase
from conductor.config import Config
from conductor.state import RunState, now_ts


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
    consensus = propose_phase._find_contradiction_consensus(records, required_count=2)
    assert consensus is not None
    assert len(consensus["models"]) == 2


def test_find_contradiction_consensus_different_quotes():
    records = [
        ("claude", {"spec_contradictions": [{"quote": "A", "why_conflicts": "x", "resolution_options": ["1"]}]}),
        ("codex", {"spec_contradictions": [{"quote": "B", "why_conflicts": "y", "resolution_options": ["1"]}]}),
    ]
    consensus = propose_phase._find_contradiction_consensus(records, required_count=2)
    assert consensus is None


def test_find_contradiction_consensus_normalizes_quotes():
    records = [
        (
            "claude",
            {"spec_contradictions": [{"quote": "Use   SQLite", "why_conflicts": "x", "resolution_options": ["1"]}]},
        ),
        (
            "codex",
            {"spec_contradictions": [{"quote": " use sqlite ", "why_conflicts": "y", "resolution_options": ["1"]}]},
        ),
    ]
    consensus = propose_phase._find_contradiction_consensus(records, required_count=2)
    assert consensus is not None
    assert consensus["models"] == ["claude", "codex"]
    assert consensus["quote"] == "Use SQLite"


def test_run_propose_does_not_block_for_different_contradictions(tmp_path, monkeypatch):
    responses = iter([
        {"spec_contradictions": [{"quote": "Use SQLite", "why_conflicts": "x", "resolution_options": ["A"]}]},
        {"spec_contradictions": [{"quote": "No auth", "why_conflicts": "y", "resolution_options": ["B"]}]},
        {"spec_contradictions": []},
    ])

    def fake_invoke_model_safe(**kwargs):
        return next(responses), 0.0, None

    monkeypatch.setattr(propose_phase, "invoke_model_safe", fake_invoke_model_safe)
    monkeypatch.setattr(propose_phase, "validate", lambda data, schema: [])
    monkeypatch.setattr(propose_phase, "render_prompt", lambda name, variables: "prompt")

    state = RunState(run_id="r-diff", started_at=now_ts(), phase="PROPOSE")
    result = propose_phase.run_propose(
        state=state,
        config=Config(),
        task_text="task",
        run_dir=tmp_path / "run",
    )

    assert result["blocked"] is False
    assert state.phase == "SYNTHESIZE"


def test_run_propose_blocks_for_same_quote_consensus(tmp_path, monkeypatch):
    responses = iter([
        {"spec_contradictions": [{"quote": "Use SQLite", "why_conflicts": "x", "resolution_options": ["A"]}]},
        {"spec_contradictions": [{"quote": "Use SQLite", "why_conflicts": "y", "resolution_options": ["B"]}]},
        {"spec_contradictions": []},
    ])

    def fake_invoke_model_safe(**kwargs):
        return next(responses), 0.0, None

    monkeypatch.setattr(propose_phase, "invoke_model_safe", fake_invoke_model_safe)
    monkeypatch.setattr(propose_phase, "validate", lambda data, schema: [])
    monkeypatch.setattr(propose_phase, "render_prompt", lambda name, variables: "prompt")

    state = RunState(run_id="r-same", started_at=now_ts(), phase="PROPOSE")
    result = propose_phase.run_propose(
        state=state,
        config=Config(),
        task_text="task",
        run_dir=tmp_path / "run",
    )

    assert result["blocked"] is True
    assert state.phase == "REPORT"
    assert "use sqlite" in result["reason"].lower()


def test_run_propose_blocks_for_normalized_quote_consensus(tmp_path, monkeypatch):
    responses = iter([
        {"spec_contradictions": [{"quote": "Use   SQLite", "why_conflicts": "x", "resolution_options": ["A"]}]},
        {"spec_contradictions": [{"quote": " use sqlite ", "why_conflicts": "y", "resolution_options": ["B"]}]},
        {"spec_contradictions": []},
    ])

    def fake_invoke_model_safe(**kwargs):
        return next(responses), 0.0, None

    monkeypatch.setattr(propose_phase, "invoke_model_safe", fake_invoke_model_safe)
    monkeypatch.setattr(propose_phase, "validate", lambda data, schema: [])
    monkeypatch.setattr(propose_phase, "render_prompt", lambda name, variables: "prompt")

    state = RunState(run_id="r-norm", started_at=now_ts(), phase="PROPOSE")
    result = propose_phase.run_propose(
        state=state,
        config=Config(),
        task_text="task",
        run_dir=tmp_path / "run",
    )

    assert result["blocked"] is True
    assert state.phase == "REPORT"
    assert "Use SQLite" in result["reason"]
