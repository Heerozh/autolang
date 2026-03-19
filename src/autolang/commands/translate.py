"""Implementation for the `autolang translate` command."""

from __future__ import annotations

import re
from argparse import Namespace
from collections import defaultdict
from pathlib import Path

import polib
from tqdm import tqdm

from autolang.babel import compile_catalogs, discover_locales, locale_catalog_path
from autolang.config import get_domain
from autolang.i18n import _
from autolang.translator import OpenAITranslator, ReferenceTranslation, TranslationInput


def run(args: Namespace) -> int:
    """Translate untranslated PO entries grouped by locale and source file."""
    domain = get_domain()
    if not args.model:
        raise RuntimeError(
            _("Missing model configuration. Set --model or AUTOLANG_MODEL/OPENAI_MODEL.")
        )
    if not args.base_url:
        raise RuntimeError(
            _("Missing base URL configuration. Set --base-url or AUTOLANG_BASE_URL/OPENAI_BASE_URL.")
        )
    if args.batch_size <= 0:
        raise RuntimeError(_("--batch-size must be greater than 0."))

    prompt_path = Path(args.directory) / "PROMPT.md"
    system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else None
    translator = OpenAITranslator(
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        system_prompt=system_prompt,
    )

    locales = discover_locales(args.directory)
    for locale in locales:
        po_path = locale_catalog_path(args.directory, locale, domain)
        if not po_path.exists():
            continue

        catalog = polib.pofile(str(po_path))
        translate_catalog(
            catalog=catalog,
            po_path=po_path,
            locale=locale,
            sources=args.sources,
            translator=translator,
            batch_size=args.batch_size,
        )

    exit_code = compile_catalogs(directory=args.directory, domain=domain, locales=locales)
    if exit_code != 0:
        return exit_code

    return 0


def translate_catalog(
    *,
    catalog: polib.POFile,
    po_path: Path,
    locale: str,
    sources: list[str],
    translator: OpenAITranslator,
    batch_size: int,
) -> bool:
    """Translate a single locale catalog in place."""
    source_roots = {normalize_source_root(source) for source in sources}
    plural_indexes = get_plural_indexes(catalog)
    grouped_entries = collect_untranslated_entries(
        catalog,
        source_roots=source_roots,
    )
    if not grouped_entries:
        return False

    total = sum(len(entries) for entries in grouped_entries.values())
    translated_any = False
    with tqdm(total=total, desc=locale, unit=_("entry")) as progress:
        for source_file, entries in sorted(grouped_entries.items()):
            references = collect_reference_translations(
                catalog,
                source_file=source_file,
                plural_indexes=plural_indexes,
            )
            for batch in batched(entries, batch_size):
                outputs = translator.translate_batch(
                    target_language=locale,
                    source_file=source_file,
                    entries=build_translation_inputs(batch, plural_indexes=plural_indexes),
                    references=references,
                )
                for entry, output in zip(batch, outputs, strict=True):
                    if not entry.msgid_plural:
                        if output.text is None:
                            raise RuntimeError(_("Singular translation response is missing text."))
                        entry.msgstr = output.text
                    else:
                        if output.plural_texts is None:
                            raise RuntimeError(
                                _("Plural translation response is missing plural_texts.")
                            )
                        apply_plural_translation(
                            entry,
                            plural_texts=output.plural_texts,
                            plural_indexes=plural_indexes,
                        )
                progress.update(len(batch))
                translated_any = True
                catalog.save(str(po_path))

    return translated_any


def collect_untranslated_entries(
    catalog: polib.POFile,
    *,
    source_roots: set[str],
) -> dict[str, list[polib.POEntry]]:
    """Collect untranslated entries grouped by source file."""
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
    plural_indexes: list[int],
) -> list[ReferenceTranslation]:
    """Collect translated entries from the same source file as context."""
    references: list[ReferenceTranslation] = []
    for entry in catalog:
        if not is_translated_entry(entry):
            continue
        if normalize_occurrence(primary_occurrence(entry)) != source_file:
            continue
        if not entry.msgid_plural:
            references.append(
                ReferenceTranslation(
                    source_text=entry.msgid,
                    translated_text=entry.msgstr,
                    context=entry.msgctxt,
                )
            )
            continue

        references.append(
            ReferenceTranslation(
                source_text=entry.msgid,
                context=entry.msgctxt,
                plural_source_text=entry.msgid_plural,
                translated_plural_texts=[
                    entry.msgstr_plural.get(index, "")
                    for index in plural_indexes
                ],
            )
        )
    return references


def should_translate_entry(
    entry: polib.POEntry,
) -> bool:
    """Return whether a PO entry should be sent to the model."""
    if entry.obsolete:
        return False
    if entry.msgid == "":
        return False
    return not entry.translated()


def is_translated_entry(
    entry: polib.POEntry,
) -> bool:
    """Return whether the entry is translated."""
    if entry.obsolete:
        return False
    if entry.msgid == "":
        return False
    return entry.translated()


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


def build_translation_inputs(
    entries: list[polib.POEntry],
    *,
    plural_indexes: list[int],
) -> list[TranslationInput]:
    """Convert PO entries into translator request objects."""
    inputs: list[TranslationInput] = []
    for entry in entries:
        if not entry.msgid_plural:
            inputs.append(
                TranslationInput(
                    text=entry.msgid,
                    context=entry.msgctxt,
                    comment=build_entry_comment(entry),
                )
            )
            continue

        inputs.append(
            TranslationInput(
                text=entry.msgid,
                plural_text=entry.msgid_plural,
                expected_plural_forms=len(plural_indexes),
                context=entry.msgctxt,
                comment=build_entry_comment(entry),
            )
        )
    return inputs


def apply_plural_translation(
    entry: polib.POEntry,
    *,
    plural_texts: list[str],
    plural_indexes: list[int],
) -> None:
    """Write plural translation forms back into a PO entry."""
    if len(plural_texts) != len(plural_indexes):
        raise RuntimeError(_("Plural translation count does not match target plural slots."))
    for index, text in zip(plural_indexes, plural_texts, strict=True):
        entry.msgstr_plural[index] = text


def get_plural_indexes(catalog: polib.POFile) -> list[int]:
    """Return the plural slot indexes required by the target catalog."""
    plural_forms = catalog.metadata.get("Plural-Forms", "")
    match = re.search(r"nplurals\s*=\s*(\d+)", plural_forms)
    if match is None:
        return [0, 1]

    plural_count = int(match.group(1))
    if plural_count <= 0:
        return [0]
    return list(range(plural_count))


def batched(
    entries: list[polib.POEntry],
    batch_size: int,
) -> list[list[polib.POEntry]]:
    """Split entries into fixed-size batches."""
    return [
        entries[index : index + batch_size]
        for index in range(0, len(entries), batch_size)
    ]
