"""Implementation for the `autolang translate` command."""

from __future__ import annotations

from collections import defaultdict
from argparse import Namespace
from pathlib import Path

import polib

from autolang.babel import discover_locales, locale_catalog_path
from autolang.translator import OpenAITranslator, ReferenceTranslation, TranslationInput


def run(args: Namespace) -> int:
    """Translate untranslated PO entries grouped by locale and source file."""
    if not args.model:
        raise RuntimeError(
            "Missing model configuration. Set --model or AUTOLANG_MODEL/OPENAI_MODEL."
        )
    if not args.base_url:
        raise RuntimeError(
            "Missing base URL configuration. Set --base-url or AUTOLANG_BASE_URL/OPENAI_BASE_URL."
        )
    if args.batch_size <= 0:
        raise RuntimeError("--batch-size must be greater than 0.")

    prompt_path = Path(args.directory) / "PROMPT.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else None
    translator = OpenAITranslator(
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        system_prompt=system_prompt,
    )

    for locale in discover_locales(args.directory):
        po_path = locale_catalog_path(args.directory, locale, args.domain)
        if not po_path.exists():
            continue

        catalog = polib.pofile(str(po_path))
        translated_any = translate_catalog(
            catalog=catalog,
            locale=locale,
            sources=args.sources,
            translator=translator,
            batch_size=args.batch_size,
        )
        if translated_any:
            catalog.save(str(po_path))

    return 0


def translate_catalog(
    *,
    catalog: polib.POFile,
    locale: str,
    sources: list[str],
    translator: OpenAITranslator,
    batch_size: int,
) -> bool:
    """Translate a single locale catalog in place."""
    source_roots = {normalize_source_root(source) for source in sources}
    grouped_entries = collect_untranslated_entries(catalog, source_roots=source_roots)
    if not grouped_entries:
        return False

    translated_any = False
    for source_file, entries in sorted(grouped_entries.items()):
        references = collect_reference_translations(catalog, source_file=source_file)
        for batch in batched(entries, batch_size):
            outputs = translator.translate_batch(
                target_language=locale,
                source_file=source_file,
                entries=[
                    TranslationInput(
                        text=entry.msgid,
                        context=entry.msgctxt,
                        comment=build_entry_comment(entry),
                    )
                    for entry in batch
                ],
                references=references,
            )
            for entry, output in zip(batch, outputs, strict=True):
                entry.msgstr = output.text
                translated_any = True

    return translated_any


def collect_untranslated_entries(
    catalog: polib.POFile,
    *,
    source_roots: set[str],
) -> dict[str, list[polib.POEntry]]:
    """Collect untranslated singular entries grouped by source file."""
    grouped: dict[str, list[polib.POEntry]] = defaultdict(list)
    for entry in catalog:
        if not should_translate_entry(entry):
            continue
        source_file = select_source_file(entry, source_roots=source_roots)
        grouped[source_file].append(entry)
    return dict(grouped)


def collect_reference_translations(
    catalog: polib.POFile,
    *,
    source_file: str,
) -> list[ReferenceTranslation]:
    """Collect translated entries from the same source file as context."""
    references: list[ReferenceTranslation] = []
    for entry in catalog:
        if not is_translated_singular_entry(entry):
            continue
        if primary_occurrence(entry) != source_file:
            continue
        references.append(
            ReferenceTranslation(
                source_text=entry.msgid,
                translated_text=entry.msgstr,
                context=entry.msgctxt,
            )
        )
    return references


def should_translate_entry(entry: polib.POEntry) -> bool:
    """Return whether a PO entry should be sent to the model."""
    if entry.obsolete:
        return False
    if entry.msgid == "":
        return False
    if entry.msgid_plural:
        return False
    return not entry.translated()


def is_translated_singular_entry(entry: polib.POEntry) -> bool:
    """Return whether the entry is a translated singular message."""
    if entry.obsolete:
        return False
    if entry.msgid == "":
        return False
    if entry.msgid_plural:
        return False
    return entry.translated() and bool(entry.msgstr)


def primary_occurrence(entry: polib.POEntry) -> str:
    """Return the entry's primary source file."""
    if entry.occurrences:
        return entry.occurrences[0][0]
    return "<unknown>"


def select_source_file(entry: polib.POEntry, *, source_roots: set[str]) -> str:
    """Choose the source file key used to batch an entry."""
    for filename, _lineno in entry.occurrences:
        normalized = normalize_occurrence(filename)
        if not source_roots or any(
            normalized == root or normalized.startswith(f"{root}/")
            for root in source_roots
            if root != "."
        ):
            return normalized

    primary = normalize_occurrence(primary_occurrence(entry))
    if "." in source_roots:
        return primary
    return primary


def normalize_source_root(source: str) -> str:
    """Normalize source roots passed via CLI."""
    normalized = Path(source).as_posix()
    if normalized in {"", "."}:
        return "."
    return normalized.rstrip("/")


def normalize_occurrence(filename: str) -> str:
    """Normalize a Babel occurrence path."""
    return Path(filename).as_posix().lstrip("./") or "."


def build_entry_comment(entry: polib.POEntry) -> str | None:
    """Collapse PO comments into a prompt-friendly string."""
    comments: list[str] = []
    if entry.comment:
        comments.append(entry.comment)
    if entry.tcomment:
        comments.append(entry.tcomment)
    if not comments:
        return None
    return "\n".join(comments)


def batched(
    entries: list[polib.POEntry],
    batch_size: int,
) -> list[list[polib.POEntry]]:
    """Split entries into fixed-size batches."""
    return [
        entries[index : index + batch_size]
        for index in range(0, len(entries), batch_size)
    ]
