"""Tests for conductor.schema_validator module."""

import pytest

from conductor.schema_validator import validate, validate_or_raise


def test_validate_proposal_valid(example_proposal):
    errors = validate(example_proposal, "proposal")
    assert errors == []


def test_validate_master_plan_valid(example_master_plan):
    errors = validate(example_master_plan, "master_plan")
    assert errors == []


def test_validate_build_update_valid(example_build_update):
    errors = validate(example_build_update, "build_update")
    assert errors == []


def test_validate_review_valid(example_review):
    errors = validate(example_review, "review")
    assert errors == []


def test_validate_qa_valid(example_qa):
    errors = validate(example_qa, "qa")
    assert errors == []


def test_validate_optimization_valid(example_optimization):
    errors = validate(example_optimization, "optimization")
    assert errors == []


def test_validate_final_report_valid(example_final_report):
    errors = validate(example_final_report, "final_report")
    assert errors == []


def test_validate_blocked_report_valid(example_blocked_report):
    errors = validate(example_blocked_report, "blocked_report")
    assert errors == []


def test_validate_invalid_proposal():
    errors = validate({"kind": "proposal"}, "proposal")
    assert len(errors) > 0


def test_validate_or_raise_invalid():
    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_or_raise({"bad": "data"}, "proposal")


def test_validate_or_raise_valid(example_proposal):
    validate_or_raise(example_proposal, "proposal")  # Should not raise
