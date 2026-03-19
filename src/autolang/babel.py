"""Thin wrappers around Babel CLI commands used by autolang."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from babel.messages.frontend import CommandLineInterface


def catalog_path(directory: str | Path, domain: str) -> Path:
    """Return the POT file path for the configured domain."""
    return Path(directory) / f"{domain}.pot"


def locale_catalog_path(directory: str | Path, locale: str, domain: str) -> Path:
    """Return the PO file path for a locale/domain pair."""
    return Path(directory) / locale / "LC_MESSAGES" / f"{domain}.po"


def discover_locales(directory: str | Path) -> list[str]:
    """Discover locale directories beneath the catalog directory."""
    output_dir = Path(directory)
    if not output_dir.exists():
        return []

    locales = [
        child.name
        for child in output_dir.iterdir()
        if child.is_dir() and (child / "LC_MESSAGES").exists()
    ]
    return sorted(locales)


def extract_catalog(
    *, directory: str | Path, domain: str, sources: Sequence[str]
) -> int:
    """Extract messages from source files into the domain POT file."""
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    return run_babel(
        [
            "extract",
            "--output-file",
            str(catalog_path(output_dir, domain)),
            *sources,
        ]
    )


def init_catalog(*, directory: str | Path, domain: str, locale: str) -> int:
    """Initialize a locale catalog from the extracted POT file."""
    return run_babel(
        [
            "init",
            "--input-file",
            str(catalog_path(directory, domain)),
            "--output-dir",
            str(directory),
            "--domain",
            domain,
            "--locale",
            locale,
        ]
    )


def update_catalogs(
    *, directory: str | Path, domain: str, locales: Sequence[str]
) -> int:
    """Update locale catalogs from the extracted POT file."""
    for locale in locales:
        exit_code = run_babel(
            [
                "update",
                "--input-file",
                str(catalog_path(directory, domain)),
                "--output-dir",
                str(directory),
                "--domain",
                domain,
                "--locale",
                locale,
                "--init-missing",
                "--ignore-obsolete",
            ]
        )
        if exit_code != 0:
            return exit_code
    return 0


def run_babel(argv: Sequence[str]) -> int:
    """Run the Babel CLI in-process and normalize its exit code."""
    cli = CommandLineInterface()
    try:
        result = cli.run(["pybabel", *argv])
    except SystemExit as exc:
        return _normalize_exit_code(exc.code)
    return _normalize_exit_code(result)


def _normalize_exit_code(code: object | None) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1
