"""Shared pytest fixtures for the autolang test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and enter a temporary project directory for CLI integration tests."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
