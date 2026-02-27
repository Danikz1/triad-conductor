"""Shared fixtures for tests."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
SCHEMAS_DIR = ROOT / "schemas"


@pytest.fixture
def tmp_dir():
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def example_proposal():
    return json.loads((EXAMPLES_DIR / "proposal.json").read_text())


@pytest.fixture
def example_master_plan():
    return json.loads((EXAMPLES_DIR / "master_plan.json").read_text())


@pytest.fixture
def example_build_update():
    return json.loads((EXAMPLES_DIR / "build_update.json").read_text())


@pytest.fixture
def example_review():
    return json.loads((EXAMPLES_DIR / "review.json").read_text())


@pytest.fixture
def example_qa():
    return json.loads((EXAMPLES_DIR / "qa.json").read_text())


@pytest.fixture
def example_optimization():
    return json.loads((EXAMPLES_DIR / "optimization.json").read_text())


@pytest.fixture
def example_final_report():
    return json.loads((EXAMPLES_DIR / "final_report.json").read_text())


@pytest.fixture
def example_blocked_report():
    return json.loads((EXAMPLES_DIR / "blocked_report.json").read_text())


@pytest.fixture
def sample_config_path():
    return ROOT / "config.yaml"


@pytest.fixture
def sample_task(tmp_dir):
    task = tmp_dir / "task.md"
    task.write_text("# Sample Task\n\nBuild a hello world CLI app.\n", encoding="utf-8")
    return task
