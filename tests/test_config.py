"""Tests for conductor.config module."""

from conductor.config import load_config, Config


def test_load_config(sample_config_path):
    cfg = load_config(sample_config_path)
    assert isinstance(cfg, Config)
    assert cfg.project_name == "triad-conductor"
    assert cfg.base_branch == "main"
    assert cfg.max_wall_time_minutes == 90
    assert cfg.max_total_cost_usd == 25
    assert cfg.max_build_iterations == 5
    assert len(cfg.proposer_models) == 3
    assert cfg.arbiter_model.name == "claude"
    assert cfg.builder_model.name == "codex"
    assert cfg.qa_model.name == "gemini"
    assert cfg.tournament_enabled is True
    assert len(cfg.denylist_globs) > 0


def test_config_defaults():
    cfg = Config()
    assert cfg.max_wall_time_minutes == 90
    assert cfg.optimize_enabled is True
    assert cfg.max_optimize_passes == 2


def test_load_config_overrides(tmp_dir):
    cfg_file = tmp_dir / "test_config.yaml"
    cfg_file.write_text("""
project:
  name: "my-project"
  base_branch: "develop"
run_limits:
  max_wall_time_minutes: 30
  max_total_cost_usd: 10
""", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.project_name == "my-project"
    assert cfg.base_branch == "develop"
    assert cfg.max_wall_time_minutes == 30
    assert cfg.max_total_cost_usd == 10
    # Defaults should still apply for unset values
    assert cfg.max_build_iterations == 5
