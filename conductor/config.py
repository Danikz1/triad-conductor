"""YAML configuration loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ModelRef:
    name: str
    role: str
    model: str | None = None


@dataclass
class Config:
    project_name: str = "triad-conductor"
    base_branch: str = "main"

    # Run limits
    max_wall_time_minutes: int = 90
    max_total_cost_usd: float = 25.0
    max_total_tool_calls: int = 200

    # Phase limits
    propose_timeout_minutes: int = 8
    max_build_iterations: int = 5
    max_stuck_replans: int = 1
    max_review_loops: int = 3
    optimize_enabled: bool = True
    max_optimize_passes: int = 2

    # Tournament
    tournament_enabled: bool = True
    tournament_triggers: list[str] = field(default_factory=lambda: [
        "stuck_detector_fired_once",
        "arbiter_requests_tournament",
        "two_root_cause_hypotheses",
    ])

    # Models
    proposer_models: list[ModelRef] = field(default_factory=lambda: [
        ModelRef("claude", "proposer"),
        ModelRef("codex", "proposer"),
        ModelRef("gemini", "proposer"),
    ])
    arbiter_model: ModelRef = field(default_factory=lambda: ModelRef("claude", "arbiter"))
    builder_model: ModelRef = field(default_factory=lambda: ModelRef("codex", "builder"))
    reviewer_model: ModelRef = field(default_factory=lambda: ModelRef("claude", "reviewer"))
    qa_model: ModelRef = field(default_factory=lambda: ModelRef("gemini", "qa"))
    optimizer_models: list[ModelRef] = field(default_factory=lambda: [
        ModelRef("claude", "optimizer"),
        ModelRef("codex", "optimizer"),
        ModelRef("gemini", "optimizer"),
    ])

    # Git
    branch_prefix: str = "run"
    worktrees_dir: str = "worktrees"

    # Artifacts
    runs_dir: str = "runs"
    store_screenshots: bool = True
    store_test_logs: bool = True
    redact_before_model: bool = True

    # Security
    denylist_globs: list[str] = field(default_factory=lambda: [
        "**/.env", "**/.env.*", "**/*secret*", "**/*key*",
        "**/id_rsa*", "**/.ssh/**", "**/Library/Keychains/**",
    ])


def _parse_model_ref(d: dict[str, str]) -> ModelRef:
    return ModelRef(
        name=d["name"],
        role=d["role"],
        model=d.get("model"),
    )


def load_config(path: Path) -> Config:
    """Load a YAML config file and return a Config dataclass."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    cfg = Config()

    # Project
    proj = raw.get("project", {})
    cfg.project_name = proj.get("name", cfg.project_name)
    cfg.base_branch = proj.get("base_branch", cfg.base_branch)

    # Run limits
    rl = raw.get("run_limits", {})
    cfg.max_wall_time_minutes = rl.get("max_wall_time_minutes", cfg.max_wall_time_minutes)
    cfg.max_total_cost_usd = rl.get("max_total_cost_usd", cfg.max_total_cost_usd)
    cfg.max_total_tool_calls = rl.get("max_total_tool_calls", cfg.max_total_tool_calls)

    # Phase limits
    pl = raw.get("phase_limits", {})
    prop = pl.get("propose", {})
    cfg.propose_timeout_minutes = prop.get("timeout_minutes", cfg.propose_timeout_minutes)
    bld = pl.get("build", {})
    cfg.max_build_iterations = bld.get("max_iterations", cfg.max_build_iterations)
    cfg.max_stuck_replans = bld.get("max_stuck_replans", cfg.max_stuck_replans)
    cc = pl.get("cross_check", {})
    cfg.max_review_loops = cc.get("max_review_loops", cfg.max_review_loops)
    opt = pl.get("optimize", {})
    cfg.optimize_enabled = opt.get("enabled", cfg.optimize_enabled)
    cfg.max_optimize_passes = opt.get("max_passes", cfg.max_optimize_passes)

    # Tournament
    tm = raw.get("tournament_mode", {})
    cfg.tournament_enabled = tm.get("enabled", cfg.tournament_enabled)
    cfg.tournament_triggers = tm.get("trigger_if", cfg.tournament_triggers)

    # Models
    models = raw.get("models", {})
    if "proposer_models" in models:
        cfg.proposer_models = [_parse_model_ref(m) for m in models["proposer_models"]]
    if "arbiter_model" in models:
        cfg.arbiter_model = _parse_model_ref(models["arbiter_model"])
    if "builder_model" in models:
        cfg.builder_model = _parse_model_ref(models["builder_model"])
    if "reviewer_model" in models:
        cfg.reviewer_model = _parse_model_ref(models["reviewer_model"])
    if "qa_model" in models:
        cfg.qa_model = _parse_model_ref(models["qa_model"])
    if "optimizer_models" in models:
        cfg.optimizer_models = [_parse_model_ref(m) for m in models["optimizer_models"]]

    # Git
    git = raw.get("git", {})
    cfg.branch_prefix = git.get("branch_prefix", cfg.branch_prefix)
    cfg.worktrees_dir = git.get("worktrees_dir", cfg.worktrees_dir)

    # Artifacts
    art = raw.get("artifacts", {})
    cfg.runs_dir = art.get("runs_dir", cfg.runs_dir)
    cfg.store_screenshots = art.get("store_screenshots", cfg.store_screenshots)
    cfg.store_test_logs = art.get("store_test_logs", cfg.store_test_logs)
    cfg.redact_before_model = art.get("redact_before_model", cfg.redact_before_model)

    # Security
    sec = raw.get("security", {})
    cfg.denylist_globs = sec.get("denylist_globs", cfg.denylist_globs)

    return cfg
