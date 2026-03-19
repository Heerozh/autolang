"""Integration tests for the `autolang init` command."""

from __future__ import annotations

from pathlib import Path

from autolang.cli import main


def test_init_creates_catalogs_for_each_locale(sample_project: Path) -> None:
    write_source(
        sample_project / "app.py",
        [
            "hello",
            "goodbye",
        ],
    )

    exit_code = main(
        [
            "init",
            "-d",
            "locales",
            "-D",
            "messages",
            "-l",
            "en",
            "-l",
            "zh",
            "--source",
            ".",
        ]
    )

    assert exit_code == 0
    assert (sample_project / "locales" / "messages.pot").exists()
    assert (sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po").exists()
    assert (sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po").exists()


def write_source(path: Path, messages: list[str]) -> None:
    body = "\n".join(f'print(_("{message}"))' for message in messages)
    path.write_text(
        "from gettext import gettext as _\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
