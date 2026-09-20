"""Concurrency and incremental persistence tests for translation batches."""

from __future__ import annotations

from pathlib import Path
from threading import Barrier, Event, Lock, get_ident

import polib
import pytest

from autolang.cli import main
from autolang.commands.translate import translate_catalog
from autolang.translator import (
    OpenAITranslator,
    ReferenceTranslation,
    TranslationInput,
    TranslationOutput,
    TranslatorResponseError,
)


def make_catalog(path: Path, *, shared_file: bool = True) -> polib.POFile:
    catalog = polib.POFile()
    catalog.metadata = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Plural-Forms": "nplurals=2; plural=(n != 1);",
    }
    for index in range(8):
        source_file = "src/shared.py" if shared_file else f"src/file{index}.py"
        catalog.append(
            polib.POEntry(
                msgid=f"message-{index}",
                msgid_plural=f"messages-{index}" if index % 2 else "",
                flags=["fuzzy", "python-brace-format"],
                occurrences=[(source_file, "1")],
            )
        )
        if index == 0 or not shared_file:
            catalog.append(
                polib.POEntry(
                    msgid=f"reference-{index}",
                    msgstr=f"translated-reference-{index}",
                    occurrences=[(source_file, "2")],
                )
            )
    catalog.save(str(path))
    return catalog


@pytest.mark.parametrize("concurrency", [1, 2, 4])
@pytest.mark.parametrize("shared_file", [False, True])
def test_concurrent_batches_keep_references_and_write_on_calling_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    concurrency: int,
    shared_file: bool,
) -> None:
    po_path = tmp_path / "messages.po"
    catalog = make_catalog(po_path, shared_file=shared_file)
    translator = OpenAITranslator(model="test", base_url="https://example.com/v1")
    barrier = Barrier(concurrency, timeout=5)
    lock = Lock()
    active = 0
    peak = 0
    caller_thread = get_ident()
    saved_threads: list[int] = []
    save = catalog.save

    def record_save(path: str) -> None:
        saved_threads.append(get_ident())
        save(path)

    def translate_batch(
        *,
        target_language: str,
        entries: list[TranslationInput],
        source_file: str,
        references: list[ReferenceTranslation],
    ) -> list[TranslationOutput]:
        nonlocal active, peak
        assert get_ident() != caller_thread
        assert target_language == "en"
        assert len(entries) == 1
        index = int(entries[0].text.split("-")[1])
        assert source_file == (
            "src/shared.py" if shared_file else f"src/file{index}.py"
        )
        reference_index = 0 if shared_file else index
        assert references == [
            ReferenceTranslation(
                source_text=f"reference-{reference_index}",
                translated_text=f"translated-reference-{reference_index}",
            )
        ]
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait()
            if entries[0].plural_text is not None:
                assert entries[0].expected_plural_forms == 2
                return [
                    TranslationOutput(plural_texts=[f"one-{index}", f"many-{index}"])
                ]
            return [TranslationOutput(text=f"translated-{index}")]
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(catalog, "save", record_save)
    monkeypatch.setattr(translator, "translate_batch", translate_batch)

    assert translate_catalog(
        catalog=catalog,
        po_path=po_path,
        locale="en",
        sources=["src"],
        translator=translator,
        batch_size=1,
        concurrency=concurrency,
    )

    assert peak == concurrency
    assert saved_threads == [caller_thread] * 8
    result = polib.pofile(str(po_path))
    for index in range(8):
        entry = result.find(f"message-{index}")
        assert entry is not None
        assert entry.flags == ["python-brace-format"]
        if index % 2:
            assert entry.msgstr_plural == {0: f"one-{index}", 1: f"many-{index}"}
        else:
            assert entry.msgstr == f"translated-{index}"


@pytest.mark.parametrize("fail_first", [False, True])
def test_completed_batches_are_saved_while_another_request_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_first: bool
) -> None:
    po_path = tmp_path / "messages.po"
    catalog = polib.POFile()
    for message in ("first", "second"):
        catalog.append(polib.POEntry(msgid=message, occurrences=[("src/app.py", "1")]))
    catalog.save(str(po_path))
    translator = OpenAITranslator(model="test", base_url="https://example.com/v1")
    second_saved = Event()
    save = catalog.save
    snapshots: list[list[str]] = []
    error = TranslatorResponseError("bad response\nTranslation API response:\n{}")

    def record_save(path: str) -> None:
        save(path)
        snapshots.append([entry.msgstr for entry in polib.pofile(path)])
        second_saved.set()

    def translate_batch(
        *, entries: list[TranslationInput], **kwargs
    ) -> list[TranslationOutput]:
        if entries[0].text == "first":
            assert second_saved.wait(timeout=5), (
                "The completed batch was not saved promptly."
            )
            if fail_first:
                raise error
        return [TranslationOutput(text=f"translated-{entries[0].text}")]

    monkeypatch.setattr(catalog, "save", record_save)
    monkeypatch.setattr(translator, "translate_batch", translate_batch)

    def run_translation() -> bool:
        return translate_catalog(
            catalog=catalog,
            po_path=po_path,
            locale="en",
            sources=["src"],
            translator=translator,
            batch_size=1,
            concurrency=2,
        )

    if fail_first:
        with pytest.raises(TranslatorResponseError) as exc_info:
            run_translation()
        assert exc_info.value is error
        assert snapshots == [["", "translated-second"]]
    else:
        assert run_translation()
        assert snapshots == [
            ["", "translated-second"],
            ["translated-first", "translated-second"],
        ]


def test_request_failure_stops_new_batches_and_saves_inflight_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    po_path = tmp_path / "messages.po"
    catalog = make_catalog(po_path)
    translator = OpenAITranslator(model="test", base_url="https://example.com/v1")
    calls: list[str] = []
    error = TranslatorResponseError("bad response")
    failure_seen = Event()

    # Release the second request only after the coordinator observes the first failure.
    from concurrent.futures import wait

    def observe_wait(*args, **kwargs):
        result = wait(*args, **kwargs)
        failure_seen.set()
        return result

    def translate_batch(
        *, entries: list[TranslationInput], **kwargs
    ) -> list[TranslationOutput]:
        text = entries[0].text
        calls.append(text)
        if text == "message-0":
            raise error
        assert failure_seen.wait(timeout=5)
        return [TranslationOutput(plural_texts=["one", "many"])]

    monkeypatch.setattr("autolang.commands.translate.wait", observe_wait)
    monkeypatch.setattr(translator, "translate_batch", translate_batch)

    with pytest.raises(TranslatorResponseError) as exc_info:
        translate_catalog(
            catalog=catalog,
            po_path=po_path,
            locale="en",
            sources=["src"],
            translator=translator,
            batch_size=1,
            concurrency=2,
        )

    assert exc_info.value is error
    assert sorted(calls) == ["message-0", "message-1"]
    result = polib.pofile(str(po_path))
    failed = result.find("message-0")
    successful = result.find("message-1")
    assert failed is not None and "fuzzy" in failed.flags and not failed.msgstr
    assert successful is not None and "fuzzy" not in successful.flags
    assert successful.msgstr_plural == {0: "one", 1: "many"}


@pytest.mark.parametrize("concurrency", [0, -1])
def test_translate_rejects_invalid_concurrency(
    sample_project: Path, concurrency: int
) -> None:
    with pytest.raises(RuntimeError, match="--concurrency"):
        main(
            [
                "translate",
                "-d",
                "locales",
                "--source",
                "./src",
                "--model",
                "test",
                "--base-url",
                "https://example.com/v1",
                "--api-key",
                "test-key",
                "--concurrency",
                str(concurrency),
            ]
        )
