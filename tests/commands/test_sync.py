"""Integration tests for the `autolang sync` command."""

from __future__ import annotations

from pathlib import Path

import pytest
from babel.messages.pofile import read_po, write_po

from autolang.cli import main


def test_sync_adds_new_messages_and_preserves_existing_translations(
    sample_project: Path,
) -> None:
    write_source(sample_project / "src" / "app.py", ["hello"])
    assert (
        main(
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
        == 0
    )

    set_translation(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "hello",
        "Hello",
    )
    set_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
        "你好",
    )

    write_source(sample_project / "src" / "app.py", ["hello", "welcome"])
    exit_code = main(["sync", "-d", "locales", "--source", "./src"])

    assert exit_code == 0
    assert get_translation(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "hello",
    ) == "Hello"
    assert get_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
    ) == "你好"
    assert has_message(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "welcome",
    )
    assert has_message(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "welcome",
    )


def test_sync_removes_deleted_messages_from_all_locales(sample_project: Path) -> None:
    write_source(sample_project / "src" / "app.py", ["hello", "welcome"])
    assert (
        main(
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
        == 0
    )

    write_source(sample_project / "src" / "app.py", ["welcome"])
    exit_code = main(["sync", "-d", "locales", "--source", "./src"])

    assert exit_code == 0
    assert not has_message(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "hello",
    )
    assert not has_message(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
    )
    assert has_message(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "welcome",
    )
    assert has_message(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "welcome",
    )


def test_sync_extracts_tagged_translator_comments(sample_project: Path) -> None:
    write_source(sample_project / "src" / "app.py", ["welcome"])
    assert (
        main(
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
        == 0
    )

    write_source_with_comments(
        sample_project / "src" / "app.py",
        [
            ("welcome", ["NOTE: Refers to the onboarding CTA."]),
        ],
    )
    exit_code = main(["sync", "-d", "locales", "--source", "./src"])

    assert exit_code == 0
    po_text = (
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po"
    ).read_text(encoding="utf-8")
    assert "#. NOTE: Refers to the onboarding CTA." in po_text
    assert 'msgid "welcome"' in po_text


def test_sync_defaults_to_detected_package_directory(project_layout_factory) -> None:
    project_root, code_dir = project_layout_factory(package_name="demo_app", layout="src")
    write_source(code_dir / "app.py", ["hello"])
    assert main(["init", "-l", "zh"]) == 0

    set_translation(
        project_root / "src" / "demo_app" / "i18n" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
        "你好",
    )

    write_source(code_dir / "app.py", ["hello", "welcome"])
    exit_code = main(["sync"])

    assert exit_code == 0
    assert get_translation(
        project_root / "src" / "demo_app" / "i18n" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
    ) == "你好"
    assert has_message(
        project_root / "src" / "demo_app" / "i18n" / "zh" / "LC_MESSAGES" / "messages.po",
        "welcome",
    )


def test_sync_requires_pyproject_toml_in_project_root(
    sample_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (sample_project / "pyproject.toml").unlink()
    write_source(sample_project / "src" / "app.py", ["hello"])

    with pytest.raises(SystemExit) as exc_info:
        main(["sync", "-d", "locales", "--source", "./src"])

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


def set_translation(path: Path, msgid: str, msgstr: str) -> None:
    with path.open("r", encoding="utf-8") as fileobj:
        catalog = read_po(fileobj)

    message = catalog.get(msgid)
    assert message is not None
    message.string = msgstr

    with path.open("wb") as fileobj:
        write_po(fileobj, catalog)


def get_translation(path: Path, msgid: str) -> str | None:
    with path.open("r", encoding="utf-8") as fileobj:
        catalog = read_po(fileobj)

    message = catalog.get(msgid)
    assert message is not None
    return message.string


def has_message(path: Path, msgid: str) -> bool:
    with path.open("r", encoding="utf-8") as fileobj:
        catalog = read_po(fileobj)

    return catalog.get(msgid) is not None


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
