from __future__ import annotations

import argparse
from pathlib import Path

from babel.messages.extract import extract, extract_from_dir

from ..toml_io import load_string_table, write_string_table
from .common import NO_TRANSLATION, build_source_cue_path, list_locale_files, should_recurse_into_directory

TT_EXTRACTION_METHOD = "autolang.cli.extractors:extract_tt_python"
TT_EXTRACTION_KEYWORDS = {"tt": None}


def handle_sync_command(args: argparse.Namespace) -> int:
    source_path = Path(args.source)
    locale_dir = Path(args.locale_dir)

    extracted_cues, scanned_files = collect_source_templates(source_path)
    unique_messages = list(extracted_cues)
    locale_files = list_locale_files(locale_dir)

    if not locale_files:
        raise SystemExit(
            f"No locale TOML files found in {locale_dir}. Run `tt init --source {source_path} --locale-dir {locale_dir} --locales <locale>...` first."
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
                synced_entries[message] = NO_TRANSLATION
                total_added_entries += 1
        total_removed_entries += len(set(current_entries) - set(unique_messages))
        synced_locale_entries[locale_path] = synced_entries

    if not args.dry_run:
        for locale_path, synced_entries in synced_locale_entries.items():
            write_string_table(str(locale_path), synced_entries)
            write_string_table(str(build_source_cue_path(locale_dir, locale_path.stem)), extracted_cues)
        cue_dir = locale_dir.parent / f".{locale_dir.name}_cue"
        active_cue_names = {f"{locale_path.stem}.toml" for locale_path in locale_files}
        for cue_path in sorted(cue_dir.glob("*.toml")):
            if cue_path.is_file() and cue_path.name not in active_cue_names:
                cue_path.unlink()

    print(
        f"Scanned {scanned_files} Python file(s), synced {len(locale_files)} locale file(s), "
        f"tracked {len(unique_messages)} template(s), added {total_added_entries} missing entry/entries, "
        f"removed {total_removed_entries} stale entry/entries."
    )
    return 0


def collect_source_templates(source_path: Path) -> tuple[dict[str, str], int]:
    if not source_path.exists():
        raise SystemExit(f"Source path not found: {source_path}")

    if source_path.is_file():
        if source_path.suffix != ".py":
            raise SystemExit(f"Source path must be a Python file or directory: {source_path}")
        return extract_templates_from_file(source_path), 1

    scanned_files: set[str] = set()
    extracted = extract_from_dir(
        str(source_path),
        method_map=[("**.py", TT_EXTRACTION_METHOD)],
        keywords=TT_EXTRACTION_KEYWORDS,
        callback=build_extraction_callback(scanned_files),
        directory_filter=should_recurse_into_directory,
    )
    cues: dict[str, str] = {}
    for _filename, _lineno, message, comments, _context in extracted:
        if not isinstance(message, str) or not message:
            continue
        cues.setdefault(message, comments[0] if comments else "")
    return cues, len(scanned_files)


def extract_templates_from_file(source_path: Path) -> dict[str, str]:
    with source_path.open("rb") as fileobj:
        extracted = extract(
            TT_EXTRACTION_METHOD,
            fileobj,
            keywords=TT_EXTRACTION_KEYWORDS,
            options={"filename": str(source_path)},
        )
        cues: dict[str, str] = {}
        for _lineno, message, comments, _context in extracted:
            if isinstance(message, str) and message:
                cues.setdefault(message, comments[0] if comments else "")
        return cues


def build_extraction_callback(scanned_files: set[str]):
    def callback(filename: str, method: str, options: dict[str, object]) -> None:
        del method
        scanned_files.add(filename)
        options["filename"] = filename

    return callback
