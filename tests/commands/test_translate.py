"""Integration tests for the `autolang translate` command."""

from __future__ import annotations

from pathlib import Path

import polib

from autolang.cli import main
from autolang.translator import TranslationOutput


def test_translate_groups_by_source_file_and_uses_prompt_context(
    sample_project: Path,
    monkeypatch,
) -> None:
    write_source(sample_project / "app.py", ["hello", "welcome"])
    write_source(sample_project / "admin.py", ["save"])

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
                ".",
            ]
        )
        == 0
    )

    (sample_project / "locales" / "PROMPT.md").write_text(
        "Do not translate Autolang.\nPrefer concise UI text.\n",
        encoding="utf-8",
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

    captured_inits: list[dict[str, object]] = []
    captured_calls: list[dict[str, object]] = []

    class FakeTranslator:
        def __init__(
            self,
            *,
            model: str,
            base_url: str,
            api_key: str | None = None,
            system_prompt: str | None = None,
            timeout: float = 60.0,
            temperature: float = 0.0,
        ) -> None:
            captured_inits.append(
                {
                    "model": model,
                    "base_url": base_url,
                    "api_key": api_key,
                    "system_prompt": system_prompt,
                    "timeout": timeout,
                    "temperature": temperature,
                }
            )

        def translate_batch(
            self,
            *,
            target_language: str,
            entries,
            source_file: str | None = None,
            references=None,
        ) -> list[TranslationOutput]:
            captured_calls.append(
                {
                    "target_language": target_language,
                    "source_file": source_file,
                    "entries": [(entry.text, entry.context, entry.comment) for entry in entries],
                    "references": [
                        (
                            reference.source_text,
                            reference.translated_text,
                            reference.context,
                        )
                        for reference in (references or [])
                    ],
                }
            )
            return [
                TranslationOutput(text=f"{target_language}:{entry.text}")
                for entry in entries
            ]

    monkeypatch.setattr("autolang.commands.translate.OpenAITranslator", FakeTranslator)

    exit_code = main(
        [
            "translate",
            "-d",
            "locales",
            "--source",
            ".",
            "--model",
            "gpt-test",
            "--base-url",
            "https://example.com/v1",
        ]
    )

    assert exit_code == 0
    assert captured_inits == [
        {
            "model": "gpt-test",
            "base_url": "https://example.com/v1",
            "api_key": None,
            "system_prompt": "Do not translate Autolang.\nPrefer concise UI text.\n",
            "timeout": 60.0,
            "temperature": 0.0,
        }
    ]
    assert captured_calls == [
        {
            "target_language": "en",
            "source_file": "admin.py",
            "entries": [("save", None, None)],
            "references": [],
        },
        {
            "target_language": "en",
            "source_file": "app.py",
            "entries": [("welcome", None, None)],
            "references": [("hello", "Hello", None)],
        },
        {
            "target_language": "zh",
            "source_file": "admin.py",
            "entries": [("save", None, None)],
            "references": [],
        },
        {
            "target_language": "zh",
            "source_file": "app.py",
            "entries": [("welcome", None, None)],
            "references": [("hello", "你好", None)],
        },
    ]

    assert get_translation(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "hello",
    ) == "Hello"
    assert get_translation(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "welcome",
    ) == "en:welcome"
    assert get_translation(
        sample_project / "locales" / "en" / "LC_MESSAGES" / "messages.po",
        "save",
    ) == "en:save"
    assert get_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
    ) == "你好"
    assert get_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "welcome",
    ) == "zh:welcome"
    assert get_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "save",
    ) == "zh:save"


def test_translate_skips_when_no_untranslated_entries(
    sample_project: Path,
    monkeypatch,
) -> None:
    write_source(sample_project / "app.py", ["hello"])
    assert (
        main(
            [
                "init",
                "-d",
                "locales",
                "-l",
                "zh",
                "--source",
                ".",
            ]
        )
        == 0
    )
    set_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
        "你好",
    )

    calls: list[str] = []

    class FakeTranslator:
        def __init__(self, **kwargs) -> None:
            calls.append("init")

        def translate_batch(self, **kwargs):
            calls.append("translate")
            return []

    monkeypatch.setattr("autolang.commands.translate.OpenAITranslator", FakeTranslator)

    exit_code = main(
        [
            "translate",
            "-d",
            "locales",
            "--source",
            ".",
            "--model",
            "gpt-test",
            "--base-url",
            "https://example.com/v1",
        ]
    )

    assert exit_code == 0
    assert calls == ["init"]
    assert get_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
    ) == "你好"


def write_source(path: Path, messages: list[str]) -> None:
    body = "\n".join(f'print(_("{message}"))' for message in messages)
    path.write_text(
        "from gettext import gettext as _\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


def set_translation(path: Path, msgid: str, msgstr: str) -> None:
    catalog = polib.pofile(str(path))
    entry = catalog.find(msgid)
    assert entry is not None
    entry.msgstr = msgstr
    catalog.save()


def get_translation(path: Path, msgid: str) -> str:
    catalog = polib.pofile(str(path))
    entry = catalog.find(msgid)
    assert entry is not None
    assert entry.msgstr
    return entry.msgstr
