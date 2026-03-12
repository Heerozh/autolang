import pytest
from datetime import datetime
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from transparentlation import TransparentTranslator, install
from babel.support import Format
from babel import Locale

# To prevent NameError before _() catches the frame, we export a dummy fmt obj
fmt = Format(Locale.parse("en"))


@pytest.fixture(autouse=True)
def setup_translator():
    test_locales_dir = os.path.join(os.path.dirname(__file__), "locales")
    return install("es", test_locales_dir)


def test_basic_translation(setup_translator):
    name = "Alice"
    result = setup_translator.translate(f"Hello {name}")
    assert result == "Hola Alice"


def test_fallback_untranslated(setup_translator):
    # Cold start should fallback to original string if not in TOML
    result = setup_translator.translate(f"Untranslated string")
    assert result == "Untranslated string"


def test_currency_formatting(setup_translator):
    balance = 1234.56
    result = setup_translator.translate(f"Account balance: {fmt.currency(balance, 'USD')}")
    # In Spanish locale, Babel formats currency differently (e.g., using commas or symbol placement)
    # The expected output may be something like "Saldo de la cuenta: 1234,56 US$"

    # We mainly test that the formatting didn't crash and substitution occurred.
    assert "Saldo de la cuenta: " in result
    assert "1.234" in result


def test_date_formatting(setup_translator):
    now = datetime(2026, 3, 11)
    result = setup_translator.translate(f"Today is {fmt.date(now, format='short')}")
    # In Spanish (es), short date is often DD/MM/YY
    assert "Hoy es 11/3/26" in result or "Hoy es 11/03/26" in result


def test_hot_path_caching(setup_translator):
    # Test that calling the same exact line multiple times uses the cached bytecode
    name = "CachedUser"

    def wrapped_call():
        return setup_translator.translate(f"Hello {name}")

    assert wrapped_call() == "Hola CachedUser"
    assert wrapped_call() == "Hola CachedUser"


def test_reload_invalidates_instance_cache(tmp_path):
    locale_file = tmp_path / "es.toml"
    locale_file.write_text('"Hello {name}" = "Hola {name}"\n', encoding="utf-8")

    translator = TransparentTranslator("es", str(tmp_path))
    name = "Alice"

    def wrapped_call():
        return translator.translate(f"Hello {name}")

    assert wrapped_call() == "Hola Alice"

    locale_file.write_text('"Hello {name}" = "Buenas {name}"\n', encoding="utf-8")
    translator.reload()

    assert wrapped_call() == "Buenas Alice"


def test_translator_instances_keep_separate_caches(tmp_path):
    (tmp_path / "es.toml").write_text('"Hello {name}" = "Hola {name}"\n', encoding="utf-8")
    (tmp_path / "fr.toml").write_text('"Hello {name}" = "Bonjour {name}"\n', encoding="utf-8")

    es_translator = TransparentTranslator("es", str(tmp_path))
    fr_translator = TransparentTranslator("fr", str(tmp_path))
    name = "Alice"

    def call_translate(translator):
        return translator.translate(f"Hello {name}")

    assert call_translate(es_translator) == "Hola Alice"
    assert call_translate(fr_translator) == "Bonjour Alice"
    assert call_translate(es_translator) == "Hola Alice"


def test_translation_eval_errors_fall_back_to_source_text(tmp_path):
    (tmp_path / "es.toml").write_text('"Hello {name}" = "Hola {missing}"\n', encoding="utf-8")

    translator = TransparentTranslator("es", str(tmp_path))
    name = "Alice"

    result = translator.translate(f"Hello {name}")

    assert result == "Hello Alice"


def test_f_string_format_spec_is_preserved_in_translation_key(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Price: {price:.2f}" = "Precio: {price:.2f}"\n',
        encoding="utf-8",
    )

    translator = TransparentTranslator("es", str(tmp_path))
    price = 12.345

    assert translator.translate(f"Price: {price:.2f}") == "Precio: 12.35"


def test_f_string_conversion_is_preserved_in_translation_key(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Debug: {obj!r}" = "Depurar: {obj!r}"\n',
        encoding="utf-8",
    )

    translator = TransparentTranslator("es", str(tmp_path))

    class Demo:
        def __repr__(self) -> str:
            return "<demo>"

    obj = Demo()

    assert translator.translate(f"Debug: {obj!r}") == "Depurar: <demo>"


def test_f_string_conversion_and_nested_format_spec_are_preserved(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Value: {value!s:>{width}}" = "Valor: {value!s:>{width}}"\n',
        encoding="utf-8",
    )

    translator = TransparentTranslator("es", str(tmp_path))
    value = 7
    width = 4

    assert translator.translate(f"Value: {value!s:>{width}}") == "Valor:    7"


def test_missing_translation_is_collected_into_toml(tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    translator = TransparentTranslator("es", str(locale_dir), collect_missing=True)
    name = "Alice"

    result = translator.translate(f"Hello {name}")

    assert result == "Hello Alice"
    assert (locale_dir / "es.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello {name}"\n'
    )
    assert (tmp_path / ".locales_cue" / "es.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello Alice"\n'
    )


def test_missing_translation_is_collected_into_all_configured_locales(tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    translator = TransparentTranslator(
        "es",
        str(locale_dir),
        collect_missing=True,
        collect_locales=["en", "es", "fr"],
    )
    name = "Alice"

    assert translator.translate(f"Hello {name}") == "Hello Alice"
    assert (locale_dir / "en.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello {name}"\n'
    )
    assert (locale_dir / "es.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello {name}"\n'
    )
    assert (locale_dir / "fr.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello {name}"\n'
    )
    assert (tmp_path / ".locales_cue" / "en.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello Alice"\n'
    )
    assert (tmp_path / ".locales_cue" / "es.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello Alice"\n'
    )
    assert (tmp_path / ".locales_cue" / "fr.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello Alice"\n'
    )


def test_collection_keeps_existing_translations(tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    locale_file = locale_dir / "es.toml"
    locale_file.write_text('"Hello {name}" = "Hola {name}"\n', encoding="utf-8")

    translator = TransparentTranslator("es", str(locale_dir), collect_missing=True)
    name = "Alice"

    assert translator.translate(f"Hello {name}") == "Hola Alice"
    assert translator.translate("Untranslated string") == "Untranslated string"

    assert locale_file.read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hola {name}"\n'
        '"Untranslated string" = "Untranslated string"\n'
    )
    assert (tmp_path / ".locales_cue" / "es.toml").read_text(encoding="utf-8") == (
        '"Untranslated string" = "Untranslated string"\n'
    )
