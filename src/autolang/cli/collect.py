from __future__ import annotations

import argparse
from pathlib import Path

from babel.messages.extract import extract, extract_from_dir

from ..toml_io import load_string_table, write_string_table
from .common import build_source_cue_path, normalize_language, should_recurse_into_directory

TT_EXTRACTION_METHOD = "autolang.cli.extractors:extract_tt_python"
TT_EXTRACTION_KEYWORDS = {"tt": None}


def handle_collect_command(args: argparse.Namespace) -> int:
    source_path = Path(args.source)
    locale_dir = Path(args.locale_dir)
    source_locale = normalize_language(args.source_locale)

    extracted_cues, scanned_files = collect_source_templates(source_path)
    unique_messages = list(extracted_cues)

    locale_path = locale_dir / f"{source_locale}.toml"
    cue_path = build_source_cue_path(locale_dir, source_locale)
    source_entries = load_string_table(str(locale_path))
    source_cues = load_string_table(str(cue_path))
    added_entries = 0

    for message in unique_messages:
        if message not in source_entries:
            source_entries[message] = message
            added_entries += 1
        source_cues[message] = extracted_cues.get(message, "")

    if not args.dry_run:
        write_string_table(str(locale_path), source_entries)
        write_string_table(str(cue_path), source_cues)

    print(
        f"Scanned {scanned_files} Python file(s), collected {len(unique_messages)} template(s), "
        f"added {added_entries} new entry/entries."
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
