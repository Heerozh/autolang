import os
import sys
from datetime import datetime

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from babel import Locale
from babel.support import Format

from autolang import TransparentTranslator, install

# To prevent NameError before _() catches the frame, we export a dummy fmt obj
fmt = Format(Locale.parse("en"))


@pytest.fixture(autouse=True)
def setup_translator():
    test_locales_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "locales")
    )
    return install(test_locales_dir, "es")


def test_basic_translation(setup_translator):
    name = "Alice"
    result = setup_translator.translate(f"Hello {name}")
    assert result == "Hola Alice"


def test_fallback_untranslated(setup_translator):
    # Cold start should fallback to original string if not in TOML
    result = setup_translator.translate("Untranslated string")
    assert result == "Untranslated string"


def test_currency_formatting(setup_translator):
    balance = 1234.56
    result = setup_translator.translate(
        f"Account balance: {fmt.currency(balance, 'USD')}"
    )
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
    (tmp_path / "es.toml").write_text(
        '"Hello {name}" = "Hola {name}"\n', encoding="utf-8"
    )
    (tmp_path / "fr.toml").write_text(
        '"Hello {name}" = "Bonjour {name}"\n', encoding="utf-8"
    )

    es_translator = TransparentTranslator("es", str(tmp_path))
    fr_translator = TransparentTranslator("fr", str(tmp_path))
    name = "Alice"

    def call_translate(translator):
        return translator.translate(f"Hello {name}")

    assert call_translate(es_translator) == "Hola Alice"
    assert call_translate(fr_translator) == "Bonjour Alice"
    assert call_translate(es_translator) == "Hola Alice"


def test_translation_eval_errors_fall_back_to_source_text(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Hello {name}" = "Hola {missing}"\n', encoding="utf-8"
    )

    translator = TransparentTranslator("es", str(tmp_path))
    name = "Alice"

    result = translator.translate(f"Hello {name}")

    assert result == "Hello Alice"


def test_translator_uses_script_specific_locale_file(tmp_path):
    (tmp_path / "zh.toml").write_text(
        '"Hello {name}" = "中文 {name}"\n', encoding="utf-8"
    )
    (tmp_path / "zh_Hans.toml").write_text(
        '"Hello {name}" = "简体 {name}"\n',
        encoding="utf-8",
    )

    translator = TransparentTranslator("zh_Hans", str(tmp_path))
    name = "Alice"

    assert translator.translate(f"Hello {name}") == "简体 Alice"


def test_translator_loads_full_locale_with_fallback_chain(tmp_path):
    (tmp_path / "zh.toml").write_text(
        '"General" = "中文"\n"Hello {name}" = "中文 {name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "zh_Hans.toml").write_text(
        '"Hello {name}" = "简体 {name}"\n"ScriptOnly" = "简体专用"\n',
        encoding="utf-8",
    )
    (tmp_path / "zh_Hans_CN.toml").write_text(
        '"Hello {name}" = "中国简体 {name}"\n',
        encoding="utf-8",
    )

    translator = TransparentTranslator("zh_Hans_CN", str(tmp_path))
    name = "Alice"

    assert translator.translate(f"Hello {name}") == "中国简体 Alice"
    assert translator.get_translation("ScriptOnly") == "简体专用"
    assert translator.get_translation("General") == "中文"


def test_missing_translation_marker_falls_back_to_source_text(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Hello {name}" = "MISSING_TRANSLATION"\n',
        encoding="utf-8",
    )

    translator = TransparentTranslator("es", str(tmp_path))
    name = "Alice"

    assert translator.get_translation("Hello {name}") == "Hello {name}"
    assert translator.translate(f"Hello {name}") == "Hello Alice"


def test_missing_translation_marker_does_not_override_fallback_translation(tmp_path):
    (tmp_path / "zh.toml").write_text(
        '"Hello {name}" = "中文 {name}"\n',
        encoding="utf-8",
    )
    (tmp_path / "zh_Hans.toml").write_text(
        '"Hello {name}" = "MISSING_TRANSLATION"\n',
        encoding="utf-8",
    )

    translator = TransparentTranslator("zh_Hans", str(tmp_path))
    name = "Alice"

    assert translator.get_translation("Hello {name}") == "中文 {name}"
    assert translator.translate(f"Hello {name}") == "中文 Alice"


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
