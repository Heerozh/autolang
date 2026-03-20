"""Shared pytest fixtures for the autolang test suite."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def sample_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create and enter a temporary project directory for CLI integration tests."""
    monkeypatch.chdir(tmp_path)
    write_pyproject(tmp_path, package_name="sample_app", layout="src")
    return tmp_path


@pytest.fixture
def project_layout_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Create package directories and pyproject metadata for layout-sensitive tests."""
    monkeypatch.chdir(tmp_path)

    def create(*, package_name: str, layout: str) -> tuple[Path, Path]:
        write_pyproject(tmp_path, package_name=package_name, layout=layout)
        if layout == "src":
            code_dir = tmp_path / "src" / package_name
        else:
            code_dir = tmp_path / package_name
        code_dir.mkdir(parents=True, exist_ok=True)
        (code_dir / "__init__.py").write_text("", encoding="utf-8")
        return tmp_path, code_dir

    return create


def write_pyproject(project_root: Path, *, package_name: str, layout: str) -> None:
    package_search_root = 'where = ["src"]\n' if layout == "src" else ""
    pyproject_text = dedent(
        f"""
        [build-system]
        requires = ["setuptools>=80"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "{package_name.replace('_', '-')}"
        version = "0.0.0"

        [project.scripts]
        {package_name} = "{package_name}:main"

        [tool.setuptools.packages.find]
        {package_search_root}
        """
    ).lstrip()
    (project_root / "pyproject.toml").write_text(pyproject_text, encoding="utf-8")
