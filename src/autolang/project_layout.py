"""Helpers for resolving project code directories from pyproject metadata."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autolang.i18n import _

MISSING_PYPROJECT_MESSAGE = _(
    "Run autolang from the project root and ensure pyproject.toml exists."
)
UNKNOWN_CODE_DIRECTORY_MESSAGE = _(
    "Could not determine the project code directory from pyproject.toml."
)


class ProjectLayoutError(RuntimeError):
    """Raised when the project layout cannot be determined."""


@dataclass(frozen=True)
class ProjectLayout:
    """Resolved paths used for default CLI values."""

    code_directory: Path

    @property
    def catalog_directory(self) -> Path:
        return self.code_directory / "i18n"

    @property
    def source_directories(self) -> list[str]:
        return [self.code_directory.as_posix()]


def ensure_project_root(project_root: Path | None = None) -> Path:
    """Return the project pyproject path or raise if the cwd is not a project root."""
    root = project_root or Path.cwd()
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        raise ProjectLayoutError(MISSING_PYPROJECT_MESSAGE)
    return pyproject_path


def resolve_project_layout(project_root: Path | None = None) -> ProjectLayout:
    """Resolve the Python package code directory from pyproject metadata."""
    root = project_root or Path.cwd()
    pyproject_path = ensure_project_root(root)
    metadata = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    package_search_root = root / _package_search_root(metadata)

    for package_name in _package_name_candidates(metadata):
        package_directory = package_search_root / package_name
        if (package_directory / "__init__.py").exists():
            return ProjectLayout(code_directory=package_directory.relative_to(root))

    package_directories = [
        child
        for child in package_search_root.iterdir()
        if child.is_dir() and (child / "__init__.py").exists()
    ]
    if len(package_directories) == 1:
        return ProjectLayout(code_directory=package_directories[0].relative_to(root))

    raise ProjectLayoutError(UNKNOWN_CODE_DIRECTORY_MESSAGE)


def _package_search_root(metadata: dict[str, Any]) -> Path:
    where = (
        metadata.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("where")
    )
    if isinstance(where, list) and where:
        first = where[0]
        if isinstance(first, str) and first:
            return Path(first)
    return Path(".")


def _package_name_candidates(metadata: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    project = metadata.get("project", {})
    if isinstance(project, dict):
        scripts = project.get("scripts", {})
        if isinstance(scripts, dict):
            for value in scripts.values():
                if not isinstance(value, str):
                    continue
                module_path = value.split(":", 1)[0]
                top_level_package = module_path.split(".", 1)[0]
                normalized = _normalize_package_name(top_level_package)
                if normalized and normalized not in candidates:
                    candidates.append(normalized)

        project_name = project.get("name")
        if isinstance(project_name, str):
            normalized = _normalize_package_name(project_name)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

    return candidates


def _normalize_package_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", name.replace("-", "_")).strip("_")
    return normalized
