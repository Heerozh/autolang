import os
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from autolang import cli
from autolang.cli import common as cli_common
from autolang.cli import init as cli_init
from autolang.cli import sync as cli_sync
from autolang.cli import translate as cli_translate
from autolang.toml_io import load_string_table


class FakeBatchClient:
    recorded_requests = []
    recorded_extra_prompts = []

    def __init__(self, *args, **kwargs):
        type(self).recorded_extra_prompts.append(kwargs.get("extra_system_prompt"))

    def translate_batch(self, request):
        type(self).recorded_requests.append(request)
        results = {}

        for target in request.targets:
            if target.locale == "es":
                if request.key == "Hello {name}":
                    text = "Hola {name}"
                else:
                    text = f"ES {request.source_text}"
            elif target.locale == "fr":
                if request.key == "Hello {name}":
                    text = "Bonjour {name}"
                else:
                    text = f"FR {request.source_text}"
            else:
                text = f"{target.locale} {request.source_text}"

            results[target.locale] = cli.TranslationResult(
                locale=target.locale,
                text=text,
            )

        return results


class InvalidPlaceholderClient:
    def __init__(self, *args, **kwargs):
        pass

    def translate_batch(self, request):
        target = request.targets[0]
        return {
            target.locale: cli.TranslationResult(
                locale=target.locale,
                text="Hola {other}",
            )
        }


def test_cli_modules_share_the_same_tt_wrapper():
    assert cli.tt is cli_init.tt
    assert cli.tt is cli_sync.tt
    assert cli.tt is cli_translate.tt


def test_tt_sync_routes_errors_through_shared_tt(monkeypatch, tmp_path):
    missing_source = tmp_path / "missing"
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()

    monkeypatch.setattr(cli_sync, "tt", lambda text: f"[cli]{text}", raising=False)

    with pytest.raises(SystemExit, match=r"^\[cli\]Source path not found: "):
        cli.main(
            [
                "sync",
                "--source",
                str(missing_source),
                "--locale-dir",
                str(locale_dir),
            ]
        )


def test_build_extraction_callback_normalizes_relative_filenames(tmp_path):
    source_root = tmp_path / "src"
    source_root.mkdir()
    options: dict[str, object] = {}
    scanned_files: set[str] = set()

    callback = cli_sync.build_extraction_callback(scanned_files, source_root)
    callback(os.path.join("pkg", "module.py"), "python", options)

    assert options["filename"] == str(
        (source_root / Path("pkg") / "module.py").resolve()
    )


def test_resolve_locale_dir_from_source_infers_package_root_without_templates(tmp_path):
    repo_root = tmp_path / "repo"
    package_dir = repo_root / "src" / "demo_pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")

    resolved = cli_common.resolve_locale_dir_from_source(
        repo_root, Path("locales"), None
    )

    assert resolved == package_dir / "locales"


def test_tt_translate_groups_pending_locales_per_key(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locales"
    cue_dir = tmp_path / ".locales_cue"
    locale_dir.mkdir()
    cue_dir.mkdir()
    (locale_dir / "en.toml").write_text(
        '"Hello {name}" = "Hello {name}"\n"Goodbye" = "Goodbye"\n',
        encoding="utf-8",
    )
    (locale_dir / "es.toml").write_text(
        '"Goodbye" = "Adiós"\n"Hello {name}" = "MISSING_TRANSLATION"\n',
        encoding="utf-8",
    )
    (locale_dir / "fr.toml").write_text(
        '"Goodbye" = "MISSING_TRANSLATION"\n"Hello {name}" = "MISSING_TRANSLATION"\n',
        encoding="utf-8",
    )
    (cue_dir / "en.toml").write_text(
        '"Hello {name}" = "Hello Alice"\n"Goodbye" = "Goodbye"\n',
        encoding="utf-8",
    )
    (cue_dir / "es.toml").write_text(
        '"Hello {name}" = "Hello Alice"\n"Goodbye" = "Goodbye"\n',
        encoding="utf-8",
    )
    (cue_dir / "fr.toml").write_text(
        '"Hello {name}" = "Hello Alice"\n"Goodbye" = "Goodbye"\n',
        encoding="utf-8",
    )

    FakeBatchClient.recorded_requests = []
    monkeypatch.setattr(cli, "OpenAICompatibleClient", FakeBatchClient)

    exit_code = cli.main(
        [
            "translate",
            "--locale-dir",
            str(locale_dir),
            "--model",
            "demo-model",
            "--api-key",
            "demo-key",
            "--batch-size",
            "1",
            "--workers",
            "2",
        ]
    )

    assert exit_code == 0
    assert len(FakeBatchClient.recorded_requests) == 2

    hello_request = next(
        request
        for request in FakeBatchClient.recorded_requests
        if request.key == "Hello {name}"
    )
    goodbye_request = next(
        request
        for request in FakeBatchClient.recorded_requests
        if request.key == "Goodbye"
    )

    assert hello_request.cue_text == "Hello Alice"
    assert [target.locale for target in hello_request.targets] == ["es", "fr"]
    assert [target.locale for target in goodbye_request.targets] == ["fr"]
    assert all(
        request.source_text != "MISSING_TRANSLATION"
        for request in FakeBatchClient.recorded_requests
    )
    assert load_string_table(str(locale_dir / "es.toml")) == {
        "Goodbye": "Adiós",
        "Hello {name}": "Hola {name}",
    }
    assert load_string_table(str(locale_dir / "fr.toml")) == {
        "Goodbye": "FR Goodbye",
        "Hello {name}": "Bonjour {name}",
    }


def test_tt_translate_does_not_collect_source_templates(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    package_dir = repo_root / "src" / "demo_pkg"
    locale_dir = package_dir / "locales"
    cue_dir = package_dir / ".locales_cue"
    package_dir.mkdir(parents=True)
    locale_dir.mkdir()
    cue_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "app.py").write_text("print(tt('Hello'))\n", encoding="utf-8")
    (locale_dir / "en.toml").write_text('"Hello" = "Hello"\n', encoding="utf-8")
    (locale_dir / "es.toml").write_text(
        '"Hello" = "MISSING_TRANSLATION"\n', encoding="utf-8"
    )
    (cue_dir / "en.toml").write_text('"Hello" = "Greeting"\n', encoding="utf-8")
    (cue_dir / "es.toml").write_text('"Hello" = "Greeting"\n', encoding="utf-8")

    def fail_if_called(source_path):
        raise AssertionError(f"translate should not collect templates from {source_path}")

    FakeBatchClient.recorded_requests = []
    monkeypatch.setattr(cli, "OpenAICompatibleClient", FakeBatchClient)
    monkeypatch.setattr(
        cli_translate, "collect_source_templates", fail_if_called, raising=False
    )

    exit_code = cli.main(
        [
            "translate",
            "--source",
            str(repo_root),
            "--locale-dir",
            "locales",
            "--model",
            "demo-model",
            "--api-key",
            "demo-key",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "es.toml")) == {
        "Hello": "ES Hello",
    }


def test_tt_translate_dry_run_does_not_write(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locales"
    cue_dir = tmp_path / ".locales_cue"
    locale_dir.mkdir()
    cue_dir.mkdir()
    (locale_dir / "en.toml").write_text(
        '"Hello {name}" = "Hello {name}"\n', encoding="utf-8"
    )
    (locale_dir / "es.toml").write_text(
        '"Hello {name}" = "MISSING_TRANSLATION"\n', encoding="utf-8"
    )
    (cue_dir / "en.toml").write_text(
        '"Hello {name}" = "Greeting with user name"\n', encoding="utf-8"
    )
    (cue_dir / "es.toml").write_text(
        '"Hello {name}" = "Greeting with user name"\n', encoding="utf-8"
    )

    FakeBatchClient.recorded_requests = []
    monkeypatch.setattr(cli, "OpenAICompatibleClient", FakeBatchClient)

    exit_code = cli.main(
        [
            "translate",
            "--locale-dir",
            str(locale_dir),
            "--model",
            "demo-model",
            "--api-key",
            "demo-key",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "es.toml")) == {
        "Hello {name}": "MISSING_TRANSLATION",
    }


def test_tt_translate_requires_sync_when_cues_are_missing(tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    (locale_dir / "en.toml").write_text('"Hello" = "Hello"\n', encoding="utf-8")
    (locale_dir / "es.toml").write_text(
        '"Hello" = "MISSING_TRANSLATION"\n', encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="Run `tt sync"):
        cli.main(
            [
                "translate",
                "--locale-dir",
                str(locale_dir),
                "--model",
                "demo-model",
                "--api-key",
                "demo-key",
            ]
        )


def test_tt_sync_updates_all_locale_files_and_cues(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    source_dir.mkdir()
    locale_dir.mkdir()
    (source_dir / "app.py").write_text(
        "name = 'Alice'\n"
        "price = 12.345\n"
        "print(tt(f'Hello {name}'))\n"
        "print(tt(f'Price: {price:.2f}'))\n"
        "print(other(f'Ignored {name}'))\n",
        encoding="utf-8",
    )
    hidden_dir = tmp_path / ".venv"
    hidden_dir.mkdir()
    (hidden_dir / "ignored.py").write_text(
        "print(tt(f'Hidden {name}'))\n",
        encoding="utf-8",
    )
    (locale_dir / "en.toml").write_text(
        '"Existing" = "Existing"\n"Hello {name}" = "Hello {name}"\n',
        encoding="utf-8",
    )
    (locale_dir / "es.toml").write_text(
        '"Hello {name}" = "Hola {name}"\n"Obsolete" = "Obsoleto"\n',
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "sync",
            "--source",
            str(tmp_path),
            "--locale-dir",
            str(locale_dir),
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "en.toml")) == {
        "Hello {name}": "Hello {name}",
        "Price: {price:.2f}": "MISSING_TRANSLATION",
    }
    assert load_string_table(str(locale_dir / "es.toml")) == {
        "Hello {name}": "Hola {name}",
        "Price: {price:.2f}": "MISSING_TRANSLATION",
    }
    cues = load_string_table(str(tmp_path / ".locales_cue" / "en.toml"))
    assert "Template: Hello {name}" in cues["Hello {name}"]
    assert "Definition: name = 'Alice'" in cues["Hello {name}"]
    assert "Allowed candidates: {name}" in cues["Hello {name}"]
    assert "Template: Price: {price:.2f}" in cues["Price: {price:.2f}"]
    assert (
        "Source placeholder already uses an f-string format spec."
        in cues["Price: {price:.2f}"]
    )
    es_cues = load_string_table(str(tmp_path / ".locales_cue" / "es.toml"))
    assert es_cues == cues


def test_tt_init_creates_locale_files_with_no_translation_markers(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    source_dir.mkdir()
    (source_dir / "app.py").write_text(
        "print(tt('Hello'))\nprint(tt('Hola'))\nprint(tt('你好'))\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "init",
            "--source",
            str(source_dir),
            "--locale-dir",
            str(locale_dir),
            "--locales",
            "en",
            "es",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "en.toml")) == {
        "Hello": "MISSING_TRANSLATION",
        "Hola": "MISSING_TRANSLATION",
        "你好": "MISSING_TRANSLATION",
    }
    assert load_string_table(str(locale_dir / "es.toml")) == {
        "Hello": "MISSING_TRANSLATION",
        "Hola": "MISSING_TRANSLATION",
        "你好": "MISSING_TRANSLATION",
    }


def test_tt_init_resolves_relative_locale_dir_to_inferred_package_root(tmp_path):
    repo_root = tmp_path / "repo"
    package_dir = repo_root / "src" / "demo_pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "app.py").write_text(
        "print(tt('Hello'))\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "init",
            "--source",
            str(repo_root),
            "--locale-dir",
            "locales",
            "--locales",
            "en",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(package_dir / "locales" / "en.toml")) == {
        "Hello": "MISSING_TRANSLATION",
    }
    assert not (repo_root / "locales" / "en.toml").exists()


def test_tt_sync_resolves_relative_locale_dir_to_inferred_package_root(tmp_path):
    repo_root = tmp_path / "repo"
    package_dir = repo_root / "src" / "demo_pkg"
    locale_dir = package_dir / "locales"
    package_dir.mkdir(parents=True)
    locale_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "app.py").write_text(
        "print(tt('Hello'))\nprint(tt('Price'))\n",
        encoding="utf-8",
    )
    (locale_dir / "en.toml").write_text(
        '"Hello" = "Hello"\n',
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "sync",
            "--source",
            str(repo_root),
            "--locale-dir",
            "locales",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "en.toml")) == {
        "Hello": "Hello",
        "Price": "MISSING_TRANSLATION",
    }
    assert not (repo_root / "locales" / "en.toml").exists()


def test_tt_sync_dry_run_does_not_write(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    source_dir.mkdir()
    locale_dir.mkdir()
    (locale_dir / "en.toml").write_text("", encoding="utf-8")
    (source_dir / "app.py").write_text(
        "name = 'Alice'\nprint(tt(f'Hello {name}'))\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "sync",
            "--source",
            str(source_dir),
            "--locale-dir",
            str(locale_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "en.toml")) == {}
    assert load_string_table(str(tmp_path / ".locales_cue" / "en.toml")) == {}


def test_tt_sync_requires_init_when_no_locale_files_exist(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    source_dir.mkdir()
    locale_dir.mkdir()
    (source_dir / "app.py").write_text("print(tt('Hello'))\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Run `tt init"):
        cli.main(
            [
                "sync",
                "--source",
                str(source_dir),
                "--locale-dir",
                str(locale_dir),
            ]
        )


def test_tt_init_requires_force_when_locale_files_exist(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    source_dir.mkdir()
    locale_dir.mkdir()
    (source_dir / "app.py").write_text("print(tt('Hello'))\n", encoding="utf-8")
    (locale_dir / "en.toml").write_text('"Hello" = "Hola"\n', encoding="utf-8")

    with pytest.raises(SystemExit, match="--force"):
        cli.main(
            [
                "init",
                "--source",
                str(source_dir),
                "--locale-dir",
                str(locale_dir),
                "--locales",
                "en",
            ]
        )


def test_tt_init_allows_adding_new_locale_when_other_locale_files_exist(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    source_dir.mkdir()
    locale_dir.mkdir()
    (source_dir / "app.py").write_text("print(tt('Hello'))\n", encoding="utf-8")
    (locale_dir / "en.toml").write_text('"Hello" = "Hello"\n', encoding="utf-8")

    exit_code = cli.main(
        [
            "init",
            "--source",
            str(source_dir),
            "--locale-dir",
            str(locale_dir),
            "--locales",
            "zh_hans",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "en.toml")) == {"Hello": "Hello"}
    assert load_string_table(str(locale_dir / "zh_Hans.toml")) == {
        "Hello": "MISSING_TRANSLATION",
    }


def test_tt_init_force_only_replaces_requested_locales(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    cue_dir = tmp_path / ".locales_cue"
    source_dir.mkdir()
    locale_dir.mkdir()
    cue_dir.mkdir()
    (source_dir / "app.py").write_text("print(tt('Hello'))\n", encoding="utf-8")
    (locale_dir / "en.toml").write_text(
        '"Hello" = "Existing English"\n', encoding="utf-8"
    )
    (locale_dir / "zh.toml").write_text('"Hello" = "旧中文"\n', encoding="utf-8")
    (cue_dir / "en.toml").write_text('"Hello" = "existing cue"\n', encoding="utf-8")
    (cue_dir / "zh.toml").write_text('"Hello" = "旧线索"\n', encoding="utf-8")

    exit_code = cli.main(
        [
            "init",
            "--source",
            str(source_dir),
            "--locale-dir",
            str(locale_dir),
            "--locales",
            "zh_hans",
            "--force",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "en.toml")) == {
        "Hello": "Existing English",
    }
    assert load_string_table(str(locale_dir / "zh.toml")) == {
        "Hello": "旧中文",
    }
    assert load_string_table(str(locale_dir / "zh_Hans.toml")) == {
        "Hello": "MISSING_TRANSLATION",
    }
    assert load_string_table(str(cue_dir / "en.toml")) == {"Hello": "existing cue"}
    assert load_string_table(str(cue_dir / "zh.toml")) == {"Hello": "旧线索"}
    assert (
        "Template: Hello" in load_string_table(str(cue_dir / "zh_Hans.toml"))["Hello"]
    )


def test_tt_init_preserves_script_and_territory_in_locale_file_names(tmp_path):
    source_dir = tmp_path / "src"
    locale_dir = tmp_path / "locales"
    source_dir.mkdir()
    (source_dir / "app.py").write_text("print(tt('Hello'))\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "init",
            "--source",
            str(source_dir),
            "--locale-dir",
            str(locale_dir),
            "--locales",
            "zh_hans",
            "zh_hans_cn",
            "pt_br",
        ]
    )

    assert exit_code == 0
    assert (locale_dir / "zh_Hans.toml").is_file()
    assert (locale_dir / "zh_Hans_CN.toml").is_file()
    assert (locale_dir / "pt_BR.toml").is_file()


def test_tt_translate_rejects_invalid_placeholders(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locales"
    cue_dir = tmp_path / ".locales_cue"
    locale_dir.mkdir()
    cue_dir.mkdir()
    (locale_dir / "en.toml").write_text(
        '"Hello {name}" = "Hello {name}"\n', encoding="utf-8"
    )
    (locale_dir / "es.toml").write_text(
        '"Hello {name}" = "MISSING_TRANSLATION"\n', encoding="utf-8"
    )
    (cue_dir / "en.toml").write_text(
        '"Hello {name}" = "Greeting with user name"\n', encoding="utf-8"
    )
    (cue_dir / "es.toml").write_text(
        '"Hello {name}" = "Greeting with user name"\n', encoding="utf-8"
    )

    monkeypatch.setattr(cli, "OpenAICompatibleClient", InvalidPlaceholderClient)

    with pytest.raises(RuntimeError, match="placeholder"):
        cli.main(
            [
                "translate",
                "--locale-dir",
                str(locale_dir),
                "--model",
                "demo-model",
                "--api-key",
                "demo-key",
            ]
        )


def test_validate_translated_text_allows_fmt_wrappers():
    cli.validate_translated_text(
        "fee is {price}",
        '费用是{fmt.currency(price, "USD")}',
    )
    cli.validate_translated_text(
        "discount is {rate}",
        "折扣是{fmt.percent(rate / 100)}",
    )


def test_build_batch_user_prompt_describes_mixed_language_keys():
    request = cli_translate.BatchTranslationRequest(
        key="hello",
        source_text="Hola",
        cue_text="No additional cue.",
        targets=(
            cli_translate.BatchTranslationTarget(
                locale="es",
                target_language="Spanish",
            ),
            cli_translate.BatchTranslationTarget(
                locale="fr",
                target_language="French",
            ),
        ),
    )

    prompt = cli_translate.build_batch_user_prompt(request)

    assert "TOML keys" in prompt
    assert "mixed-language" in prompt
    assert "Source template:" in prompt
    assert "Target locales:" in prompt
    assert "es (Spanish)" in prompt
    assert "fr (French)" in prompt


def test_parse_batch_response_requires_all_requested_locales():
    request = cli_translate.BatchTranslationRequest(
        key="Hello",
        source_text="Hello",
        cue_text="Greeting",
        targets=(
            cli_translate.BatchTranslationTarget(
                locale="es",
                target_language="Spanish",
            ),
            cli_translate.BatchTranslationTarget(
                locale="fr",
                target_language="French",
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="locales do not match"):
        cli_translate.parse_batch_response(
            '{"translations":[{"locale":"es","text":"Hola"}]}',
            request,
        )


def test_load_translation_prompt_prefers_locale_source_then_cwd(
    tmp_path, monkeypatch
):
    locale_dir = tmp_path / "locales"
    source_dir = tmp_path / "src"
    cwd_dir = tmp_path / "cwd"
    locale_dir.mkdir()
    source_dir.mkdir()
    cwd_dir.mkdir()

    locale_prompt = locale_dir / "tt_prompt.md"
    source_prompt = source_dir / "tt_prompt.md"
    cwd_prompt = cwd_dir / "tt_prompt.md"

    locale_prompt.write_text("locale prompt", encoding="utf-8")
    source_prompt.write_text("source prompt", encoding="utf-8")
    cwd_prompt.write_text("cwd prompt", encoding="utf-8")
    monkeypatch.chdir(cwd_dir)

    assert (
        cli_translate.load_translation_prompt(source_dir, locale_dir) == "locale prompt"
    )

    locale_prompt.unlink()
    assert (
        cli_translate.load_translation_prompt(source_dir, locale_dir) == "source prompt"
    )

    source_prompt.unlink()
    assert cli_translate.load_translation_prompt(source_dir, locale_dir) == "cwd prompt"


def test_tt_translate_loads_prompt_file_for_client(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locales"
    cue_dir = tmp_path / ".locales_cue"
    source_dir = tmp_path / "src"
    locale_dir.mkdir()
    cue_dir.mkdir()
    source_dir.mkdir()
    (locale_dir / "tt_prompt.md").write_text("Use our product glossary.", encoding="utf-8")
    (locale_dir / "en.toml").write_text('"Hello" = "Hello"\n', encoding="utf-8")
    (locale_dir / "es.toml").write_text(
        '"Hello" = "MISSING_TRANSLATION"\n', encoding="utf-8"
    )
    (cue_dir / "en.toml").write_text('"Hello" = "Greeting"\n', encoding="utf-8")
    (cue_dir / "es.toml").write_text('"Hello" = "Greeting"\n', encoding="utf-8")

    FakeBatchClient.recorded_requests = []
    FakeBatchClient.recorded_extra_prompts = []
    monkeypatch.setattr(cli, "OpenAICompatibleClient", FakeBatchClient)

    exit_code = cli.main(
        [
            "translate",
            "--source",
            str(source_dir),
            "--locale-dir",
            str(locale_dir),
            "--model",
            "demo-model",
            "--api-key",
            "demo-key",
        ]
    )

    assert exit_code == 0
    assert FakeBatchClient.recorded_extra_prompts == ["Use our product glossary."]


def test_openai_client_sends_extra_system_prompt():
    client = cli_translate.OpenAICompatibleClient(
        base_url="https://example.invalid/v1",
        api_key="demo-key",
        model="demo-model",
        extra_system_prompt="Use our product glossary.",
    )
    request = cli_translate.BatchTranslationRequest(
        key="Hello",
        source_text="Hello",
        cue_text="Greeting",
        targets=(
            cli_translate.BatchTranslationTarget(
                locale="es",
                target_language="Spanish",
            ),
        ),
    )
    captured_payload: dict[str, object] = {}

    def fake_post_json(path, payload):
        captured_payload["path"] = path
        captured_payload["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"translations":[{"locale":"es","text":"Hola"}]}'
                    }
                }
            ]
        }

    client._post_json = fake_post_json  # type: ignore[method-assign]

    results = client.translate_batch(request)

    payload = captured_payload["payload"]
    assert captured_payload["path"] == "/chat/completions"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1] == {
        "role": "system",
        "content": "Use our product glossary.",
    }
    assert payload["messages"][2]["role"] == "user"
    assert results["es"].text == "Hola"
