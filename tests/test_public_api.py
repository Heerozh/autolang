import importlib
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

import autolang.translator as translator_module
from autolang import TransparentTranslator, install


def test_install_returns_translator_instance(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Hello {name}" = "Hola {name}"\n', encoding="utf-8"
    )

    translator = install(str(tmp_path), "es")

    assert isinstance(translator, TransparentTranslator)


def test_install_result_can_be_bound_to_module_level_tt(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Hello {name}" = "Hola {name}"\n', encoding="utf-8"
    )
    translator = install(str(tmp_path), "es")
    tt = translator.translate
    name = "Alice"

    assert tt(f"Hello {name}") == "Hola Alice"


def test_bound_tt_supports_f_string_conversion_and_format_spec(tmp_path):
    (tmp_path / "es.toml").write_text(
        '"Price: {price:.2f}" = "Precio: {price:.2f}"\n'
        '"Debug: {obj!r}" = "Depurar: {obj!r}"\n',
        encoding="utf-8",
    )
    translator = install(str(tmp_path), "es")
    tt = translator.translate
    price = 12.345

    class Demo:
        def __repr__(self) -> str:
            return "<demo>"

    obj = Demo()

    assert tt(f"Price: {price:.2f}") == "Precio: 12.35"
    assert tt(f"Debug: {obj!r}") == "Depurar: <demo>"


def test_install_uses_system_locale_when_locale_str_is_omitted(tmp_path, monkeypatch):
    (tmp_path / "es.toml").write_text(
        '"Hello {name}" = "Hola {name}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        translator_module.locale,
        "getlocale",
        lambda: ("es_ES", "UTF-8"),
        raising=False,
    )
    name = "Alice"

    translator = install(str(tmp_path))

    assert translator.translate(f"Hello {name}") == "Hola Alice"


def test_install_accepts_hyphenated_system_locale(tmp_path, monkeypatch):
    (tmp_path / "zh.toml").write_text(
        '"Hello {name}" = "你好 {name}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        translator_module.locale,
        "getlocale",
        lambda: ("zh-Hans-CN", "UTF-8"),
        raising=False,
    )
    name = "Alice"

    translator = install(str(tmp_path))

    assert translator.translate(f"Hello {name}") == "你好 Alice"


def test_install_accepts_windows_display_name_locale(tmp_path, monkeypatch):
    (tmp_path / "zh.toml").write_text(
        '"Hello {name}" = "你好 {name}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        translator_module.locale,
        "getlocale",
        lambda: ("Chinese (Simplified)_China", "cp936"),
        raising=False,
    )
    name = "Alice"

    translator = install(str(tmp_path))

    assert translator.translate(f"Hello {name}") == "你好 Alice"


def test_install_falls_back_to_en_when_system_locale_is_unusable(tmp_path, monkeypatch):
    (tmp_path / "en.toml").write_text(
        '"Hello {name}" = "Hello there {name}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        translator_module.locale,
        "getlocale",
        lambda: ("C", "UTF-8"),
        raising=False,
    )
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.delenv("LANGUAGE", raising=False)
    name = "Alice"

    translator = install(str(tmp_path))

    assert translator.translate(f"Hello {name}") == "Hello there Alice"


def test_install_resolves_default_locale_dir_from_caller_package_root(
    tmp_path, monkeypatch
):
    package_a = tmp_path / "package_a"
    package_b = tmp_path / "package_b"
    for package_dir, translated in (
        (package_a, "甲"),
        (package_b, "乙"),
    ):
        (package_dir / "sub").mkdir(parents=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        (package_dir / "sub" / "__init__.py").write_text("", encoding="utf-8")
        (package_dir / "locales").mkdir()
        (package_dir / "locales" / "zh.toml").write_text(
            f'"Hello {{name}}" = "{translated} {{name}}"\n',
            encoding="utf-8",
        )
        (package_dir / "sub" / "module.py").write_text(
            "from autolang import install\n"
            "translator = install(locale_str='zh')\n"
            "\n"
            "def greet(name: str) -> str:\n"
            "    return translator.translate(f'Hello {name}')\n",
            encoding="utf-8",
        )

    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    module_a = importlib.import_module("package_a.sub.module")
    module_b = importlib.import_module("package_b.sub.module")

    assert module_a.greet("Alice") == "甲 Alice"
    assert module_b.greet("Alice") == "乙 Alice"
    assert module_a.translator.locale_dir == str(package_a / "locales")
    assert module_b.translator.locale_dir == str(package_b / "locales")


def test_install_falls_back_to_caller_file_directory_for_non_package_module(
    tmp_path, monkeypatch
):
    module_dir = tmp_path / "scripts"
    module_dir.mkdir()
    (module_dir / "locales").mkdir()
    (module_dir / "locales" / "zh.toml").write_text(
        '"Hello {name}" = "脚本 {name}"\n',
        encoding="utf-8",
    )
    (module_dir / "tool.py").write_text(
        "from autolang import install\n"
        "translator = install(locale_str='zh')\n"
        "\n"
        "def greet(name: str) -> str:\n"
        "    return translator.translate(f'Hello {name}')\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(module_dir))
    importlib.invalidate_caches()
    tool = importlib.import_module("tool")

    assert tool.greet("Alice") == "脚本 Alice"
    assert tool.translator.locale_dir == str(module_dir / "locales")
