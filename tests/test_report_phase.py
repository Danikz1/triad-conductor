"""Tests for REPORT phase status classification."""

from conductor.config import Config
from conductor.phases.report import run_report
from conductor.state import RunState, now_ts


def _sample_final_report(run_id: str, status: str) -> dict:
    return {
        "kind": "final_report",
        "run_id": run_id,
        "status": status,
        "summary": "Run finished with a validated final report payload.",
        "how_to_run": ["python -m pytest -q"],
        "tests_ran": ["pytest -q"],
        "artifacts": {
            "screenshots": [],
            "logs": [],
            "test_reports": [],
            "branches": [],
        },
        "known_limitations": [],
        "next_steps": [],
    }


def _sample_blocked_report(run_id: str) -> dict:
    return {
        "kind": "blocked_report",
        "run_id": run_id,
        "status": "BLOCKED",
        "block_reason": "Spec contradictions require human decision before implementation.",
        "evidence": ["Two proposer models flagged the same conflicting requirement quote."],
        "what_was_tried": ["Parallel propose", "Arbiter synthesis pre-check"],
        "spec_change_options": [
            {
                "option": "Clarify the source-of-truth requirement and rerun.",
                "pros": ["Unblocks implementation quickly"],
                "cons": ["Needs product-owner input"],
                "impact": "Low engineering effort, immediate workflow continuity.",
            }
        ],
    }


def test_run_report_partial_uses_final_report_schema_path(tmp_path):
    run_id = "run1234"
    state = RunState(
        run_id=run_id,
        started_at=now_ts(),
        phase="REPORT",
        final_status="PARTIAL",
        breaker_reason="Review loop cap reached with unresolved issues",
    )

    result = run_report(
        state=state,
        config=Config(),
        master_plan={"milestones": []},
        context={"last_test_output": "pytest output"},
        run_dir=tmp_path / "run",
        dry_run=True,
        dry_run_response=_sample_final_report(run_id, "PARTIAL"),
    )

    assert result["status"] == "PARTIAL"
    assert (tmp_path / "run" / "artifacts" / "final_report.json").exists()
    assert not (tmp_path / "run" / "artifacts" / "blocked_report.json").exists()


def test_run_report_blocked_still_uses_blocked_report_schema_path(tmp_path):
    run_id = "run5678"
    state = RunState(
        run_id=run_id,
        started_at=now_ts(),
        phase="REPORT",
        breaker_reason="Spec contradictions detected by majority of proposers",
    )

    result = run_report(
        state=state,
        config=Config(),
        master_plan=None,
        context={},
        run_dir=tmp_path / "run",
        dry_run=True,
        dry_run_response=_sample_blocked_report(run_id),
    )

    assert result["status"] == "BLOCKED"
    assert (tmp_path / "run" / "artifacts" / "blocked_report.json").exists()
