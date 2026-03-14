from __future__ import annotations

import argparse
from pathlib import Path

from ..toml_io import write_string_table
from .common import (
    NO_TRANSLATION,
    build_source_cue_path,
    list_locale_files,
    normalize_language,
    resolve_locale_dir_from_source,
)
from .sync import collect_source_templates


def handle_init_command(args: argparse.Namespace) -> int:
    source_path = Path(args.source)
    locale_dir_arg = Path(args.locale_dir)
    locale_names = _resolve_locales(args.locales)

    extracted_cues, scanned_files, template_files = collect_source_templates(source_path)
    locale_dir = resolve_locale_dir_from_source(source_path, locale_dir_arg, template_files)
    existing_locale_files = {
        path.stem: path for path in list_locale_files(locale_dir)
    }
    requested_locale_files = {
        locale_name: locale_dir / f"{locale_name}.toml" for locale_name in locale_names
    }
    conflicting_locale_names = [
        locale_name
        for locale_name in locale_names
        if locale_name in existing_locale_files
    ]
    if conflicting_locale_names and not args.force:
        raise SystemExit(
            "Locale files already exist for "
            f"{', '.join(conflicting_locale_names)} in {locale_dir}. "
            "Re-run with --force to replace them."
        )
    entries = {message: NO_TRANSLATION for message in extracted_cues}

    if not args.dry_run:
        if args.force:
            for locale_name in conflicting_locale_names:
                requested_locale_files[locale_name].unlink()
                cue_path = build_source_cue_path(locale_dir, locale_name)
                if cue_path.is_file():
                    cue_path.unlink()

        for locale_name in locale_names:
            write_string_table(str(locale_dir / f"{locale_name}.toml"), entries)
            write_string_table(str(build_source_cue_path(locale_dir, locale_name)), extracted_cues)

    print(
        f"Scanned {scanned_files} Python file(s), initialized {len(locale_names)} locale file(s), "
        f"created {len(entries)} template entry/entries."
    )
    return 0


def _resolve_locales(locales: list[str]) -> list[str]:
    normalized: list[str] = []
    for locale in locales:
        locale_name = normalize_language(locale)
        if locale_name not in normalized:
            normalized.append(locale_name)
    return normalized
