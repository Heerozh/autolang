from __future__ import annotations

from pathlib import Path

from babel import Locale
from babel.core import UnknownLocaleError

from ..toml_io import load_string_table
from .i18n import tt

SKIPPED_SOURCE_DIR_NAMES = {
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
MISSING_TRANSLATION = "MISSING_TRANSLATION"


def load_shared_cues(locale_dir: Path) -> dict[str, str]:
    cue_dir = build_cue_dir_path(locale_dir)
    merged_cues: dict[str, str] = {}
    for cue_path in sorted(cue_dir.glob("*.toml")):
        if not cue_path.is_file():
            continue
        for key, value in load_string_table(str(cue_path)).items():
            merged_cues.setdefault(key, value)
    return merged_cues


def build_cue_dir_path(locale_dir: Path) -> Path:
    return locale_dir.parent / f".{locale_dir.name}_cue"


def build_source_cue_path(locale_dir: Path, locale_name: str) -> Path:
    cue_dir = build_cue_dir_path(locale_dir)
    return cue_dir / f"{locale_name}.toml"


def list_locale_files(locale_dir: Path) -> list[Path]:
    return sorted(path for path in locale_dir.glob("*.toml") if path.is_file())


_warned_about_tests = False


def should_recurse_into_directory(path: str) -> bool:
    global _warned_about_tests
    name = Path(path).name
    if name == "tests" and not _warned_about_tests:
        import sys

        print(
            tt(
                "Warning: A 'tests' directory was found during source scanning. "
                "Did you select the wrong --source directory? "
            ),
            file=sys.stderr,
        )
        _warned_about_tests = True
    return not name.startswith(".") and name not in SKIPPED_SOURCE_DIR_NAMES


def normalize_locale_name(locale_name: str) -> str:
    for separator in (None, "-"):
        try:
            if separator is None:
                return str(Locale.parse(locale_name))
            return str(Locale.parse(locale_name, sep=separator))
        except (ValueError, UnknownLocaleError):
            continue
    raise ValueError(f"Invalid locale identifier: {locale_name}")


def locale_display_name(locale_name: str) -> str:
    locale = Locale.parse(normalize_locale_name(locale_name))
    return str(locale.get_display_name("en")).title()


def resolve_locale_dir_from_source(
    source_path: Path, locale_dir: Path, template_files: set[Path] | None = None
) -> Path:
    if locale_dir.is_absolute():
        return locale_dir

    if not source_path.exists():
        raise SystemExit(tt(f"Source path not found: {source_path}"))

    if template_files is not None:
        return infer_package_root(source_path, template_files) / locale_dir

    inferred_root = _infer_package_root_from_source(source_path)
    if inferred_root is not None:
        return inferred_root / locale_dir

    if source_path.is_file():
        return source_path.parent.resolve() / locale_dir
    return source_path.resolve() / locale_dir


def infer_package_root(source_path: Path, template_files: set[Path]) -> Path:
    package_roots = {
        package_root
        for template_file in template_files
        if (package_root := _find_package_root_for_path(template_file)) is not None
    }
    if len(package_roots) == 1:
        return next(iter(package_roots))
    if len(package_roots) > 1:
        raise SystemExit(
            tt(
                "Multiple package roots matched the extracted templates. "
                "Pass an absolute --locale-dir or narrow --source."
            )
        )

    inferred_root = _infer_package_root_from_source(source_path)
    if inferred_root is not None:
        return inferred_root

    if source_path.is_file():
        return source_path.parent.resolve()
    return source_path.resolve()


def _infer_package_root_from_source(source_path: Path) -> Path | None:
    if source_path.is_file():
        return _find_package_root_for_path(source_path)

    direct_root = _find_package_root_for_path(source_path)
    if direct_root is not None:
        return direct_root

    package_roots = {
        package_root
        for init_file in source_path.rglob("__init__.py")
        if (package_root := _find_package_root_for_path(init_file.parent)) is not None
    }
    if len(package_roots) == 1:
        return next(iter(package_roots))
    if len(package_roots) > 1:
        raise SystemExit(
            tt(
                "Could not infer a unique package root from --source. "
                "Pass an absolute --locale-dir or narrow --source."
            )
        )

    return None


def _find_package_root_for_path(path: Path) -> Path | None:
    current = path.resolve()
    if current.is_file():
        current = current.parent

    if not (current / "__init__.py").is_file():
        return None

    package_root = current
    while (package_root.parent / "__init__.py").is_file():
        package_root = package_root.parent
    return package_root
