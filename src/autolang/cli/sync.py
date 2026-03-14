from __future__ import annotations

import argparse
from pathlib import Path

from babel.messages.extract import extract, extract_from_dir

from ..toml_io import load_string_table, write_string_table
from .common import (
    MISSING_TRANSLATION,
    build_source_cue_path,
    list_locale_files,
    resolve_locale_dir_from_source,
    should_recurse_into_directory,
)
from .i18n import tt

TT_EXTRACTION_METHOD = "autolang.cli.extractors:extract_tt_python"
TT_EXTRACTION_KEYWORDS = {"tt": None}


def handle_sync_command(args: argparse.Namespace) -> int:
    source_path = Path(args.source)
    locale_dir_arg = Path(args.locale_dir)

    extracted_cues, scanned_files, template_files = collect_source_templates(
        source_path
    )
    locale_dir = resolve_locale_dir_from_source(
        source_path, locale_dir_arg, template_files
    )
    unique_messages = list(extracted_cues)
    locale_files = list_locale_files(locale_dir)

    if not locale_files:
        raise SystemExit(
            tt(
                f"No locale TOML files found in {locale_dir}. "
                f"Run `tt init --source {source_path} --locale-dir {locale_dir} "
                f"--locales <locale>...` first."
            )
        )

    total_added_entries = 0
    total_removed_entries = 0

    synced_locale_entries: dict[Path, dict[str, str]] = {}
    for locale_path in locale_files:
        current_entries = load_string_table(str(locale_path))
        synced_entries: dict[str, str] = {}
        for message in unique_messages:
            if message in current_entries:
                synced_entries[message] = current_entries[message]
            else:
                synced_entries[message] = MISSING_TRANSLATION
                total_added_entries += 1
        total_removed_entries += len(set(current_entries) - set(unique_messages))
        synced_locale_entries[locale_path] = synced_entries

    if not args.dry_run:
        for locale_path, synced_entries in synced_locale_entries.items():
            write_string_table(str(locale_path), synced_entries)
            write_string_table(
                str(build_source_cue_path(locale_dir, locale_path.stem)), extracted_cues
            )
        cue_dir = locale_dir.parent / f".{locale_dir.name}_cue"
        active_cue_names = {f"{locale_path.stem}.toml" for locale_path in locale_files}
        for cue_path in sorted(cue_dir.glob("*.toml")):
            if cue_path.is_file() and cue_path.name not in active_cue_names:
                cue_path.unlink()

    print(
        tt(
            f"Scanned {scanned_files} Python file(s), synced {len(locale_files)} locale file(s), "
            f"tracked {len(unique_messages)} template(s), added {total_added_entries} missing entry/entries, "
            f"removed {total_removed_entries} stale entry/entries."
        )
    )
    return 0


def collect_source_templates(
    source_path: Path,
) -> tuple[dict[str, str], int, set[Path]]:
    if not source_path.exists():
        raise SystemExit(tt(f"Source path not found: {source_path}"))

    if source_path.is_file():
        if source_path.suffix != ".py":
            raise SystemExit(
                tt(f"Source path must be a Python file or directory: {source_path}")
            )
        return extract_templates_from_file(source_path), 1, {source_path.resolve()}

    scanned_files: set[str] = set()
    extracted = extract_from_dir(
        str(source_path),
        method_map=[("**.py", TT_EXTRACTION_METHOD)],
        keywords=TT_EXTRACTION_KEYWORDS,
        callback=build_extraction_callback(scanned_files, source_path),
        directory_filter=should_recurse_into_directory,
    )
    cues: dict[str, str] = {}
    template_files: set[Path] = set()
    for _filename, _lineno, message, comments, _context in extracted:
        if not isinstance(message, str) or not message:
            continue
        template_files.add(Path(_filename).resolve())
        cues.setdefault(message, comments[0] if comments else "")
    return cues, len(scanned_files), template_files


def extract_templates_from_file(source_path: Path) -> dict[str, str]:
    with source_path.open("rb") as file_obj:
        extracted = extract(
            TT_EXTRACTION_METHOD,
            file_obj,
            keywords=TT_EXTRACTION_KEYWORDS,
            options={"filename": str(source_path)},
        )
        cues: dict[str, str] = {}
        for _lineno, message, comments, _context in extracted:
            if isinstance(message, str) and message:
                cues.setdefault(message, comments[0] if comments else "")
        return cues


def build_extraction_callback(scanned_files: set[str], source_root: Path):
    def callback(filename: str, method: str, options: dict[str, object]) -> None:
        del method
        scanned_files.add(filename)
        path = Path(filename)
        if not path.is_absolute():
            path = (source_root / path).resolve()
        options["filename"] = str(path)

    return callback
