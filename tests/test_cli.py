import os
import sys

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from transparentlation import cli
from transparentlation.toml_io import load_string_table


class FakeBatchClient:
    recorded_requests = []

    def __init__(self, *args, **kwargs):
        pass

    def translate_batch(self, request):
        type(self).recorded_requests.append(request)
        results = {}

        for item in request.items:
            if request.target_locale == "es":
                if item.key == "Hello {name}":
                    text = "Hola {name}"
                else:
                    text = f"ES {item.source_text}"
            elif request.target_locale == "fr":
                if item.key == "Hello {name}":
                    text = "Bonjour {name}"
                else:
                    text = f"FR {item.source_text}"
            else:
                text = f"{request.target_locale} {item.source_text}"

            results[item.id] = cli.TranslationResult(id=item.id, text=text)

        return results


class InvalidPlaceholderClient:
    def __init__(self, *args, **kwargs):
        pass

    def translate_batch(self, request):
        item = request.items[0]
        return {
            item.id: cli.TranslationResult(id=item.id, text="Hola {other}")
        }


def test_tt_translate_uses_batches_and_cues(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locales"
    cue_dir = tmp_path / ".locales_cue"
    locale_dir.mkdir()
    cue_dir.mkdir()
    (locale_dir / "en.toml").write_text(
        '"Hello {name}" = "Hello {name}"\n'
        '"Goodbye" = "Goodbye"\n',
        encoding="utf-8",
    )
    (locale_dir / "es.toml").write_text('"Goodbye" = "Adiós"\n', encoding="utf-8")
    (locale_dir / "fr.toml").write_text("", encoding="utf-8")
    (cue_dir / "en.toml").write_text(
        '"Hello {name}" = "Hello Alice"\n'
        '"Goodbye" = "Goodbye"\n',
        encoding="utf-8",
    )

    FakeBatchClient.recorded_requests = []
    monkeypatch.setattr(cli, "OpenAICompatibleClient", FakeBatchClient)

    exit_code = cli.main(
        [
            "translate",
            "--locale-dir",
            str(locale_dir),
            "--source-locale",
            "en",
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
    assert len(FakeBatchClient.recorded_requests) == 3
    assert any(
        request.items[0].rendered_example == "Hello Alice"
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


def test_tt_translate_dry_run_does_not_write(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    (locale_dir / "en.toml").write_text('"Hello {name}" = "Hello {name}"\n', encoding="utf-8")
    (locale_dir / "es.toml").write_text("", encoding="utf-8")

    FakeBatchClient.recorded_requests = []
    monkeypatch.setattr(cli, "OpenAICompatibleClient", FakeBatchClient)

    exit_code = cli.main(
        [
            "translate",
            "--locale-dir",
            str(locale_dir),
            "--source-locale",
            "en",
            "--target-locales",
            "es",
            "--model",
            "demo-model",
            "--api-key",
            "demo-key",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert load_string_table(str(locale_dir / "es.toml")) == {}


def test_tt_translate_rejects_invalid_placeholders(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    (locale_dir / "en.toml").write_text('"Hello {name}" = "Hello {name}"\n', encoding="utf-8")
    (locale_dir / "es.toml").write_text("", encoding="utf-8")

    monkeypatch.setattr(cli, "OpenAICompatibleClient", InvalidPlaceholderClient)

    with pytest.raises(RuntimeError, match="placeholder"):
        cli.main(
            [
                "translate",
                "--locale-dir",
                str(locale_dir),
                "--source-locale",
                "en",
                "--target-locales",
                "es",
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
