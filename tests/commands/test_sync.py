"""Integration tests for the `autolang sync` command."""

from __future__ import annotations

from pathlib import Path

from babel.messages.pofile import read_po, write_po

from autolang.cli import main


def test_sync_adds_new_messages_and_preserves_existing_translations(
    sample_project: Path,
) -> None:
    write_source(sample_project / "app.py", ["hello"])
    assert (
        main(
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

    write_source(sample_project / "app.py", ["hello", "welcome"])
    exit_code = main(["sync", "-d", "locales", "--source", "."])

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
    write_source(sample_project / "app.py", ["hello", "welcome"])
    assert (
        main(
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
        == 0
    )

    write_source(sample_project / "app.py", ["welcome"])
    exit_code = main(["sync", "-d", "locales", "--source", "."])

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


def write_source(path: Path, messages: list[str]) -> None:
    body = "\n".join(f'print(_("{message}"))' for message in messages)
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
