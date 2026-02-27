"""Tests for conductor.models.invoker module (mocked subprocess)."""

from unittest.mock import patch, MagicMock

from conductor.models.invoker import invoke_model, invoke_model_safe


def test_invoke_model_dry_run():
    canned = {"kind": "proposal", "data": "test"}
    result = invoke_model("claude", "prompt", dry_run=True, dry_run_response=canned)
    assert result == canned


def test_invoke_model_dry_run_default():
    result = invoke_model("gemini", "prompt", dry_run=True)
    assert result["kind"] == "dry_run"
    assert result["model"] == "gemini"


def test_invoke_model_safe_dry_run():
    canned = {"kind": "test"}
    result, cost, err = invoke_model_safe("claude", "p", dry_run=True, dry_run_response=canned)
    assert result == canned
    assert err is None


def test_invoke_model_safe_error():
    with patch("conductor.models.invoker.invoke_model", side_effect=RuntimeError("fail")):
        result, cost, err = invoke_model_safe("claude", "prompt")
        assert result is None
        assert err is not None
        assert "fail" in err


def test_invoke_model_unknown():
    try:
        invoke_model("unknown_model", "prompt")
        assert False, "Should have raised"
    except ValueError as e:
        assert "Unknown model" in str(e)
