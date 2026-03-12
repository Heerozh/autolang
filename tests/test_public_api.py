import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from transparentlation import TransparentTranslator, install


def test_install_returns_translator_instance(tmp_path):
    (tmp_path / "es.toml").write_text('"Hello {name}" = "Hola {name}"\n', encoding="utf-8")

    translator = install("es", str(tmp_path))

    assert isinstance(translator, TransparentTranslator)


def test_install_result_can_be_bound_to_module_level_tt(tmp_path):
    (tmp_path / "es.toml").write_text('"Hello {name}" = "Hola {name}"\n', encoding="utf-8")
    translator = install("es", str(tmp_path))
    tt = translator.translate
    name = "Alice"

    assert tt(f"Hello {name}") == "Hola Alice"


def test_bound_tt_supports_f_string_conversion_and_format_spec(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Price: {price:.2f}" = "Precio: {price:.2f}"\n'
        '"Debug: {obj!r}" = "Depurar: {obj!r}"\n',
        encoding="utf-8",
    )
    translator = install("es", str(tmp_path))
    tt = translator.translate
    price = 12.345

    class Demo:
        def __repr__(self) -> str:
            return "<demo>"

    obj = Demo()

    assert tt(f"Price: {price:.2f}") == "Precio: 12.35"
    assert tt(f"Debug: {obj!r}") == "Depurar: <demo>"


def test_collect_records_runtime_text_via_instance(tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    translator = install(
        "es",
        str(locale_dir),
        collect_missing=True,
        collect_locales=["en", "es"],
    )

    assert translator.collect("runtime log line") == "runtime log line"
    assert (locale_dir / "en.toml").read_text(encoding="utf-8") == (
        '"runtime log line" = "runtime log line"\n'
    )
    assert (locale_dir / "es.toml").read_text(encoding="utf-8") == (
        '"runtime log line" = "runtime log line"\n'
    )
    assert (tmp_path / ".locales_cue" / "en.toml").read_text(encoding="utf-8") == (
        '"runtime log line" = "runtime log line"\n'
    )
    assert (tmp_path / ".locales_cue" / "es.toml").read_text(encoding="utf-8") == (
        '"runtime log line" = "runtime log line"\n'
    )


def test_collect_accepts_explicit_cue(tmp_path):
    locale_dir = tmp_path / "locales"
    locale_dir.mkdir()
    translator = install("es", str(locale_dir), collect_missing=True, collect_locales=["es"])

    assert translator.collect("Hello {name}", cue="Hello Alice") == "Hello {name}"
    assert (tmp_path / ".locales_cue" / "es.toml").read_text(encoding="utf-8") == (
        '"Hello {name}" = "Hello Alice"\n'
    )
