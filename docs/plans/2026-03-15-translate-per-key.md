# Per-Key Multi-Locale Translate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task.

**Goal:** Change `tt translate` so each model request contains one source key and asks
for translations for all pending target locales for that key.

**Architecture:** Refactor translation scheduling around source keys instead of locales.
The OpenAI-compatible request/response schema will become single-key and multi-locale,
while placeholder validation and TOML writeback stay centralized in
`src/autolang/cli/translate.py`.

**Tech Stack:** Python 3.12, argparse CLI, dataclasses, stdlib `urllib`, pytest

---

### Task 1: Lock the new request shape with tests

**Files:**

- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add a CLI test that sets up `en.toml`, `es.toml`, and `fr.toml` where one key is missing
in both target locales and another key is already translated in one locale. Assert that:

- exactly one client request is created per source key
- each request includes every pending locale for that key
- TOML writeback updates both locale files from the single request response

**Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/test_cli.py::test_tt_translate_groups_pending_locales_per_key -q`
Expected: FAIL because the current request objects are locale-oriented.

**Step 3: Write minimal implementation**

Refactor request-building logic in `src/autolang/cli/translate.py` so pending work is
grouped by source key and target locale metadata is attached under each key request.

**Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/test_cli.py::test_tt_translate_groups_pending_locales_per_key -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/autolang/cli/translate.py
git commit -m "Refactor tt translate batching by key"
```

### Task 2: Lock the new prompt and response contract

**Files:**

- Modify: `tests/test_cli.py`
- Modify: `src/autolang/cli/translate.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add tests for:

- `build_batch_user_prompt` describing one source template and multiple target locales
- response parsing/validation rejecting missing or unknown locales in the model JSON

**Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/test_cli.py -q -k "multi_locale_prompt or missing_locale_response"`
Expected: FAIL because the old prompt and parser are item-id based.

**Step 3: Write minimal implementation**

Update request/response dataclasses, prompt generation, client parsing, and validation
helpers for locale-keyed results while reusing placeholder validation.

**Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/test_cli.py -q -k "multi_locale_prompt or missing_locale_response"`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/autolang/cli/translate.py
git commit -m "Update tt translate prompt and response schema"
```

### Task 3: Verify end-to-end behavior

**Files:**

- Modify: `src/autolang/cli/__init__.py`
- Modify: `src/autolang/cli/translate.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

If needed, add a focused regression test covering `--dry-run` or placeholder rejection
through the new multi-locale response path.

**Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/test_cli.py::test_tt_translate_rejects_invalid_placeholders -q`
Expected: FAIL if the old invalid-placeholder client no longer matches the new schema.

**Step 3: Write minimal implementation**

Adjust any exported aliases or fake client expectations so the public CLI module keeps
working with the refactored request objects.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/autolang/cli/translate.py src/autolang/cli/__init__.py
git commit -m "Finish per-key multi-locale tt translate flow"
```

### Task 4: Full verification

**Files:**

- Modify: none unless fixes are needed
- Test: `tests/test_cli.py`, `tests/test_public_api.py`, `tests/test_core.py`

**Step 1: Run targeted suite**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS

**Step 2: Run broader regression suite**

Run: `uv run pytest tests/test_core.py tests/test_public_api.py tests/test_cli.py -q`
Expected: PASS

**Step 3: Run static checks if touched typing/style-sensitive code**

Run: `uv run basedpyright`
Expected: PASS

Run: `uv run ruff`
Expected: PASS
