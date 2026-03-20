"""Integration tests for the `autolang translate` command."""

from __future__ import annotations

from pathlib import Path

import polib
import pytest

from autolang.cli import main
from autolang.translator import TranslationOutput


def test_translate_groups_by_source_file_and_uses_prompt_context(
    sample_project: Path,
    monkeypatch,
) -> None:
    write_source(sample_project / "src" / "app.py", ["hello", "welcome"])
    write_source(sample_project / "src" / "admin.py", ["save"])

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
                    "entries": [
                        (
                            entry.text,
                            entry.plural_text,
                            entry.expected_plural_forms,
                            entry.context,
                            entry.comment,
                        )
                        for entry in entries
                    ],
                    "references": [
                        (
                            reference.source_text,
                            reference.plural_source_text,
                            reference.translated_text,
                            reference.translated_plural_texts,
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
            "./src",
            "--model",
            "gpt-test",
            "--base-url",
            "https://example.com/v1",
            "--api-key",
            "test-key",
        ]
    )

    assert exit_code == 0
    assert captured_inits == [
        {
            "model": "gpt-test",
            "base_url": "https://example.com/v1",
            "api_key": "test-key",
            "system_prompt": "Do not translate Autolang.\nPrefer concise UI text.\n",
            "timeout": 60.0,
            "temperature": 0.0,
        }
    ]
    assert captured_calls == [
        {
            "target_language": "en",
            "source_file": "src/admin.py",
            "entries": [("save", None, None, None, None)],
            "references": [],
        },
        {
            "target_language": "en",
            "source_file": "src/app.py",
            "entries": [("welcome", None, None, None, None)],
            "references": [("hello", None, "Hello", None, None)],
        },
        {
            "target_language": "zh",
            "source_file": "src/admin.py",
            "entries": [("save", None, None, None, None)],
            "references": [],
        },
        {
            "target_language": "zh",
            "source_file": "src/app.py",
            "entries": [("welcome", None, None, None, None)],
            "references": [("hello", None, "你好", None, None)],
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
    write_source(sample_project / "src" / "app.py", ["hello"])
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
            "./src",
            "--model",
            "gpt-test",
            "--base-url",
            "https://example.com/v1",
            "--api-key",
            "test-key",
        ]
    )

    assert exit_code == 0
    assert calls == ["init"]
    assert get_translation(
        sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po",
        "hello",
    ) == "你好"


def test_translate_backfills_plural_entries(
    sample_project: Path,
    monkeypatch,
) -> None:
    write_plural_source(sample_project / "src" / "counter.py")

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

    captured_calls: list[dict[str, object]] = []

    class FakeTranslator:
        def __init__(self, **kwargs) -> None:
            pass

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
                    "entries": [
                        (
                            entry.text,
                            entry.plural_text,
                            entry.expected_plural_forms,
                        )
                        for entry in entries
                    ],
                }
            )
            return [TranslationOutput(plural_texts=["{count} 个文件"]) for _ in entries]

    monkeypatch.setattr("autolang.commands.translate.OpenAITranslator", FakeTranslator)

    exit_code = main(
        [
            "translate",
            "-d",
            "locales",
            "--source",
            "./src",
            "--model",
            "gpt-test",
            "--base-url",
            "https://example.com/v1",
            "--api-key",
            "test-key",
        ]
    )

    assert exit_code == 0
    assert captured_calls == [
        {
            "target_language": "zh",
            "source_file": "src/counter.py",
            "entries": [("{count} file", "{count} files", 1)],
        }
    ]

    catalog = polib.pofile(str(sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po"))
    entry = catalog.find("{count} file")
    assert entry is not None
    assert entry.msgid_plural == "{count} files"
    assert entry.msgstr_plural == {0: "{count} 个文件"}


def test_translate_clears_fuzzy_flag_after_successful_writeback(
    sample_project: Path,
    monkeypatch,
) -> None:
    write_source(sample_project / "src" / "app.py", ["welcome"])
    assert main(["init", "-d", "locales", "-l", "zh", "--source", "./src"]) == 0

    catalog_path = sample_project / "locales" / "zh" / "LC_MESSAGES" / "messages.po"
    catalog = polib.pofile(str(catalog_path))
    entry = catalog.find("welcome")
    assert entry is not None
    entry.msgstr = "旧译文"
    entry.flags.append("fuzzy")
    catalog.save()

    class FakeTranslator:
        def __init__(self, **kwargs) -> None:
            pass

        def translate_batch(
            self,
            *,
            target_language: str,
            entries,
            source_file: str | None = None,
            references=None,
        ) -> list[TranslationOutput]:
            return [TranslationOutput(text="新译文") for _ in entries]

    monkeypatch.setattr("autolang.commands.translate.OpenAITranslator", FakeTranslator)

    exit_code = main(
        [
            "translate",
            "-d",
            "locales",
            "--source",
            "./src",
            "--model",
            "gpt-test",
            "--base-url",
            "https://example.com/v1",
            "--api-key",
            "test-key",
        ]
    )

    assert exit_code == 0
    updated_catalog = polib.pofile(str(catalog_path))
    updated_entry = updated_catalog.find("welcome")
    assert updated_entry is not None
    assert updated_entry.msgstr == "新译文"
    assert "fuzzy" not in updated_entry.flags


def test_translate_defaults_to_detected_package_directory(
    project_layout_factory,
    monkeypatch,
) -> None:
    project_root, code_dir = project_layout_factory(package_name="demo_app", layout="src")
    write_source(code_dir / "app.py", ["hello", "welcome"])
    write_source(code_dir / "admin.py", ["save"])
    assert main(["init", "-l", "en", "-l", "zh"]) == 0

    catalog_root = project_root / "src" / "demo_app" / "i18n"
    (catalog_root / "PROMPT.md").write_text(
        "Do not translate Autolang.\nPrefer concise UI text.\n",
        encoding="utf-8",
    )
    set_translation(catalog_root / "en" / "LC_MESSAGES" / "messages.po", "hello", "Hello")
    set_translation(catalog_root / "zh" / "LC_MESSAGES" / "messages.po", "hello", "你好")

    captured_calls: list[dict[str, object]] = []

    class FakeTranslator:
        def __init__(self, **kwargs) -> None:
            pass

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
            "--model",
            "gpt-test",
            "--base-url",
            "https://example.com/v1",
            "--api-key",
            "test-key",
        ]
    )

    assert exit_code == 0
    assert captured_calls == [
        {"target_language": "en", "source_file": "src/demo_app/admin.py"},
        {"target_language": "en", "source_file": "src/demo_app/app.py"},
        {"target_language": "zh", "source_file": "src/demo_app/admin.py"},
        {"target_language": "zh", "source_file": "src/demo_app/app.py"},
    ]
    assert get_translation(catalog_root / "en" / "LC_MESSAGES" / "messages.po", "welcome") == (
        "en:welcome"
    )
    assert get_translation(catalog_root / "zh" / "LC_MESSAGES" / "messages.po", "save") == "zh:save"


def test_translate_requires_pyproject_toml_in_project_root(
    sample_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (sample_project / "pyproject.toml").unlink()
    write_source(sample_project / "src" / "app.py", ["hello"])

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "translate",
                "--model",
                "gpt-test",
                "--base-url",
                "https://example.com/v1",
                "--api-key",
                "test-key",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "pyproject.toml" in captured.err


def write_source(path: Path, messages: list[str]) -> None:
    body = "\n".join(f'print(_("{message}"))' for message in messages)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "from gettext import gettext as _\n\n"
        f"{body}\n",
        encoding="utf-8",
    )


def write_plural_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "from gettext import ngettext\n\n"
        "def render(count: int) -> str:\n"
        '    return ngettext("{count} file", "{count} files", count)\n',
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
