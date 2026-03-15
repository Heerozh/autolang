# Translate Progress Persistence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show `tt translate` batch progress and persist successful batch results immediately so interrupted runs keep prior translations.

**Architecture:** `handle_translate_command` will stream completed batches instead of waiting for a full outcome list. A lightweight progress helper will wrap the batch iterator, using `tqdm` when available and a simple stderr progress fallback otherwise. Each completed batch will update in-memory locale entries and immediately write affected TOML files unless `--dry-run`.

**Tech Stack:** Python 3.12, `concurrent.futures`, optional `tqdm`, pytest

---

### Task 1: Add failing CLI tests for streamed persistence and progress hooks

**Files:**
- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add tests that verify:
- successful batches are written before a later batch failure
- the translate flow emits progress updates through an injectable progress factory

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_tt_translate_persists_completed_batches_before_failure tests/test_cli.py::test_tt_translate_reports_progress_for_completed_batches -q`
Expected: FAIL because translate currently writes only at the end and exposes no progress hook.

**Step 3: Write minimal implementation**

Update `src/autolang/cli/translate.py` to:
- stream completed batches
- update progress after each completed batch
- write touched locale TOML files immediately

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_tt_translate_persists_completed_batches_before_failure tests/test_cli.py::test_tt_translate_reports_progress_for_completed_batches -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/autolang/cli/translate.py docs/plans/2026-03-15-translate-progress-persistence-design.md docs/plans/2026-03-15-translate-progress-persistence.md
git commit -m "Add translate progress and incremental persistence"
```

### Task 2: Verify translation regressions remain green

**Files:**
- Modify: `src/autolang/cli/translate.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Use existing translate CLI tests as regression coverage.

**Step 2: Run test to verify behavior**

Run: `uv run pytest tests/test_cli.py -q -k 'tt_translate'`
Expected: PASS

**Step 3: Write minimal implementation**

Adjust any progress fallback or persistence details only if required by test failures.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -q -k 'tt_translate'`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/autolang/cli/translate.py
git commit -m "Verify translate CLI progress behavior"
```
