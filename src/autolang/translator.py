from __future__ import annotations

import ast
import inspect
import locale
import os
from dataclasses import dataclass
from types import CodeType, FrameType
from typing import Any

import executing
from babel import Locale
from babel.core import UnknownLocaleError
from babel.support import Format

from .source_templates import extract_template_from_call
from .toml_io import load_string_table

_ENGLISH_LOCALE = Locale.parse("en")
_MISSING_TRANSLATION = "MISSING_TRANSLATION"
_LANGUAGE_NAME_TO_CODE = {
    " ".join(name.casefold().split()): code
    for code, name in _ENGLISH_LOCALE.languages.items()
    if isinstance(name, str)
}
_SCRIPT_NAME_TO_CODE = {
    " ".join(name.casefold().split()): code
    for code, name in _ENGLISH_LOCALE.scripts.items()
    if isinstance(name, str)
}
_TERRITORY_NAME_TO_CODE = {
    " ".join(name.casefold().split()): code
    for code, name in _ENGLISH_LOCALE.territories.items()
    if isinstance(name, str)
}


@dataclass(frozen=True, slots=True)
class CacheEntry:
    template: str
    variables: tuple[str, ...]
    compiled_code: Any | None


CacheKey = tuple[str, int, str, int]


def _make_cache_key(frame: FrameType) -> CacheKey:
    code: CodeType = frame.f_code
    qualified_name = getattr(code, "co_qualname", code.co_name)
    return code.co_filename, code.co_firstlineno, qualified_name, frame.f_lasti


class TransparentTranslator:
    def __init__(
        self,
        locale_str: str = "en",
        locale_dir: str = "locales",
    ):
        self.locale = Locale.parse(locale_str)
        self.format = Format(self.locale)
        self.locale_dir = locale_dir
        self.translations: dict[str, str] = {}
        self._cache: dict[CacheKey, CacheEntry] = {}
        self.reload()

    def reload(self) -> None:
        """Reload translations for the current locale and invalidate cached call sites."""
        self.translations = self._load_translations()
        self.clear_cache()

    def clear_cache(self) -> None:
        self._cache.clear()

    def get_translation(self, source_template: str) -> str:
        translated = self.translations.get(source_template)
        if isinstance(translated, str) and translated != _MISSING_TRANSLATION:
            return translated
        return source_template

    def translate(self, text: str) -> str:
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        if caller is None:
            return text

        try:
            return self._translate_from_frame(text, caller)
        finally:
            del caller
            del frame

    def _load_translations(self) -> dict[str, str]:
        translations: dict[str, str] = {}
        for locale_name in _iter_locale_fallback_names(self.locale):
            locale_entries = load_string_table(self._locale_file_path(locale_name))
            translations.update(
                {
                    key: value
                    for key, value in locale_entries.items()
                    if value != _MISSING_TRANSLATION
                }
            )
        return translations

    def _locale_file_path(self, locale_name: str) -> str:
        return os.path.join(self.locale_dir, f"{locale_name}.toml")

    def _translate_from_frame(self, text: str, frame: FrameType) -> str:
        cache_key = _make_cache_key(frame)
        entry = self._cache.get(cache_key)

        if entry is None:
            entry = self._build_cache_entry(frame, text)
            if entry is None:
                return text
            self._cache[cache_key] = entry

        return self._evaluate(entry.compiled_code, frame, text)

    def _build_cache_entry(
        self, frame: FrameType, fallback_text: str
    ) -> CacheEntry | None:
        execution = executing.Source.executing(frame)
        node = execution.node
        template, variables = self._parse_ast_node(node)

        if template is None:
            return None

        translated = self.get_translation(template)
        compiled_code = self._compile_foreign_string(translated)
        return CacheEntry(
            template=template, variables=variables, compiled_code=compiled_code
        )

    @staticmethod
    def _parse_ast_node(node: ast.AST | None) -> tuple[str | None, tuple[str, ...]]:
        return extract_template_from_call(node)

    @staticmethod
    def _compile_foreign_string(translated: str) -> Any | None:
        try:
            return compile(f"f{translated!r}", "<autolang>", "eval")
        except Exception:
            return None

    def _evaluate(
        self, compiled_code: Any | None, frame: FrameType, fallback: str
    ) -> str:
        if compiled_code is None:
            print("WANNING: Fallback, compiled code is none")
            return fallback

        locals_proxy = frame.f_locals.copy()
        locals_proxy["fmt"] = self.format

        try:
            return eval(compiled_code, frame.f_globals, locals_proxy)
        except Exception as e:
            print("ERROR: Fallback, eval failed with exception: " + str(e))
            return fallback


def install(
    locale_dir: str = "locales",
    locale_str: str | None = None,
) -> TransparentTranslator:
    """Create a translator instance without mutating the module-level default translator."""
    frame = inspect.currentframe()
    caller = frame.f_back if frame is not None else None

    try:
        return TransparentTranslator(
            _parse_locale_str(locale_str) or _detect_system_locale(),
            _resolve_locale_dir(locale_dir, caller),
        )
    finally:
        del caller
        del frame


def _resolve_locale_dir(locale_dir: str, frame: FrameType | None) -> str:
    if os.path.isabs(locale_dir):
        return locale_dir

    return os.path.join(_resolve_caller_root_dir(frame), locale_dir)


def _resolve_caller_root_dir(frame: FrameType | None) -> str:
    if frame is None:
        return os.path.abspath(os.getcwd())

    module_file = frame.f_globals.get("__file__")
    if not isinstance(module_file, str):
        return os.path.abspath(os.getcwd())

    root_dir = os.path.dirname(os.path.abspath(module_file))
    package_name = frame.f_globals.get("__package__")
    if not isinstance(package_name, str) or not package_name:
        return root_dir

    for _ in range(max(len(package_name.split(".")) - 1, 0)):
        parent_dir = os.path.dirname(root_dir)
        if parent_dir == root_dir:
            break
        root_dir = parent_dir

    return root_dir


def _parse_locale_str(locale_str: str | None) -> str | None:
    if not locale_str:
        return None

    for separator in (None, "-"):
        try:
            if separator is None:
                return str(Locale.parse(locale_str))
            return str(Locale.parse(locale_str, sep=separator))
        except (ValueError, UnknownLocaleError):
            continue

    return _parse_windows_locale_display_name(locale_str)


def _parse_windows_locale_display_name(locale_str: str) -> str | None:
    locale_name = locale_str.split(".", 1)[0].partition("@")[0]
    if "_" not in locale_name and " (" not in locale_name:
        return None

    language_part, _separator, territory_part = locale_name.partition("_")
    script_part: str | None = None

    if language_part.endswith(")") and " (" in language_part:
        split_at = language_part.rfind(" (")
        script_part = language_part[split_at + 2 : -1]
        language_part = language_part[:split_at]

    language_code = _LANGUAGE_NAME_TO_CODE.get(
        _normalize_locale_name_part(language_part)
    )
    if language_code is None:
        return None

    script_code = None
    if script_part:
        script_code = _SCRIPT_NAME_TO_CODE.get(_normalize_locale_name_part(script_part))

    territory_code = None
    if territory_part:
        territory_code = _TERRITORY_NAME_TO_CODE.get(
            _normalize_locale_name_part(territory_part)
        )

    try:
        return str(Locale(language_code, territory=territory_code, script=script_code))
    except (ValueError, UnknownLocaleError):
        return language_code


def _normalize_locale_name_part(value: str) -> str:
    return " ".join(value.casefold().split())


def _detect_system_locale() -> str:
    locale_name, _encoding = locale.getlocale()
    for candidate in (
        locale_name,
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
        os.environ.get("LANGUAGE"),
    ):
        parsed = _parse_locale_str(candidate)
        if parsed is not None:
            return parsed

    return "en"


def _iter_locale_fallback_names(locale_obj: Locale) -> tuple[str, ...]:
    locale_names = [locale_obj.language]
    if locale_obj.script:
        locale_names.append(str(Locale(locale_obj.language, script=locale_obj.script)))
    if locale_obj.territory:
        locale_names.append(
            str(
                Locale(
                    locale_obj.language,
                    territory=locale_obj.territory,
                    script=locale_obj.script,
                )
            )
        )
    return tuple(dict.fromkeys(locale_names))
