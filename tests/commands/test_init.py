"""Integration tests for the `autolang init` command."""

from __future__ import annotations

from pathlib import Path

import pytest

from autolang.cli import main


def test_init_creates_catalogs_for_each_locale(sample_project: Path) -> None:
    write_source(
        sample_project / "src" / "app.py",
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
            "-l",
            "en",
            "-l",
            "zh",
            "--source",
            "./src",
        ]
    )

    assert exit_code == 0
    assert (sample_project / "locales" / "messages.pot").exists()
    assert (sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po").exists()
    assert (sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po").exists()


def test_init_uses_default_domain_environment_variable(
    sample_project: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEFAULT_DOMAIN", "backend")
    write_source(sample_project / "src" / "app.py", ["hello"])

    exit_code = main(
        [
            "init",
            "-d",
            "locales",
            "-l",
            "zh",
            "--source",
            "./src",
        ]
    )

    assert exit_code == 0
    assert (sample_project / "locales" / "backend.pot").exists()
    assert (sample_project / "locales" / "zh" / "LC_MESSAGES" / "backend.po").exists()


def test_init_extracts_tagged_translator_comments(sample_project: Path) -> None:
    write_source_with_comments(
        sample_project / "src" / "app.py",
        [
            ("welcome", ["NOTE: Keep this label short for the navbar."]),
        ],
    )

    exit_code = main(
        [
            "init",
            "-d",
            "locales",
            "-l",
            "zh",
            "--source",
            "./src",
        ]
    )

    assert exit_code == 0
    po_text = (
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po"
    ).read_text(encoding="utf-8")
    assert "#. NOTE: Keep this label short for the navbar." in po_text
    assert 'msgid "welcome"' in po_text


def test_init_defaults_to_detected_src_package_directory(project_layout_factory) -> None:
    project_root, code_dir = project_layout_factory(package_name="demo_app", layout="src")
    write_source(
        code_dir / "app.py",
        [
            "hello",
            "goodbye",
        ],
    )

    exit_code = main(["init", "-l", "en", "-l", "zh"])

    assert exit_code == 0
    assert (project_root / "src" / "demo_app" / "i18n" / "messages.pot").exists()
    assert (
        project_root / "src" / "demo_app" / "i18n" / "en" / "LC_MESSAGES" / "messages.po"
    ).exists()
    assert (
        project_root / "src" / "demo_app" / "i18n" / "zh" / "LC_MESSAGES" / "messages.po"
    ).exists()


def test_init_defaults_to_detected_flat_package_directory(project_layout_factory) -> None:
    project_root, code_dir = project_layout_factory(package_name="demo_app", layout="flat")
    write_source(code_dir / "app.py", ["hello"])

    exit_code = main(["init", "-l", "zh"])

    assert exit_code == 0
    assert (project_root / "demo_app" / "i18n" / "messages.pot").exists()
    assert (
        project_root / "demo_app" / "i18n" / "zh" / "LC_MESSAGES" / "messages.po"
    ).exists()


def test_init_requires_pyproject_toml_in_project_root(
    sample_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (sample_project / "pyproject.toml").unlink()
    write_source(sample_project / "src" / "app.py", ["hello"])

    with pytest.raises(SystemExit) as exc_info:
        main(["init", "-l", "zh"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "Run autolang from the project root and ensure pyproject.toml exists." in captured.err


def write_source(path: Path, messages: list[str]) -> None:
    body = "\n".join(f'print(_("{message}"))' for message in messages)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "from gettext import gettext as _\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


def write_source_with_comments(
    path: Path,
    messages: list[tuple[str, list[str]]],
) -> None:
    body_lines: list[str] = []
    for message, comments in messages:
        body_lines.extend(f"# {comment}" for comment in comments)
        body_lines.append(f'print(_("{message}"))')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "from gettext import gettext as _\n\n"
        + "\n".join(body_lines)
        + "\n",
        encoding="utf-8",
    )
