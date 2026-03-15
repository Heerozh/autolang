# TT Prompt File Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this
> plan task-by-task.

**Goal:** Let `tt translate` automatically load an optional `tt_prompt.md` file and send
its contents to the model alongside the built-in translation system prompt.

**Architecture:** Add a small prompt-discovery helper in the translate CLI that searches
a fixed set of directories in priority order. Pass the discovered prompt text into the
OpenAI-compatible client as an extra system message so built-in placeholder and JSON
constraints remain intact.

**Tech Stack:** Python 3.12, argparse CLI, stdlib `pathlib` and `urllib`, pytest

---

### Task 1: Lock prompt discovery order with tests

**Files:**

- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add a test that creates `tt_prompt.md` files under the locale directory, source
directory, and current working directory, then asserts the discovery helper chooses them
in that order.

**Step 2: Run test to verify it fails**

Run:
`uv run pytest tests/test_cli.py::test_load_translation_prompt_prefers_locale_source_then_cwd -q`
Expected: FAIL because the helper does not exist yet.

**Step 3: Write minimal implementation**

Add a helper in `src/autolang/cli/translate.py` that searches for `tt_prompt.md` under:

- `locale_dir`
- source directory
- current working directory

**Step 4: Run test to verify it passes**

Run:
`uv run pytest tests/test_cli.py::test_load_translation_prompt_prefers_locale_source_then_cwd -q`
Expected: PASS

### Task 2: Lock request integration with tests

**Files:**

- Modify: `tests/test_cli.py`
- Modify: `src/autolang/cli/translate.py`

**Step 1: Write the failing test**

Add a test that instantiates the OpenAI-compatible client with an extra prompt and
asserts the outgoing chat payload contains that prompt as an additional system message.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_openai_client_sends_extra_system_prompt -q`
Expected: FAIL because the client does not support custom prompt injection yet.

**Step 3: Write minimal implementation**

Add an optional `extra_system_prompt` argument to the client and include it in the chat
`messages` array when present.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_openai_client_sends_extra_system_prompt -q`
Expected: PASS

### Task 3: Verify end-to-end CLI behavior

**Files:**

- Modify: `README.md`
- Modify: `src/autolang/cli/translate.py`
- Test: `tests/test_cli.py`

**Step 1: Run focused CLI tests**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS

**Step 2: Run full suite**

Run: `uv run pytest -q`
Expected: PASS

**Step 3: Run lint on touched files**

Run: `uv run ruff check src/autolang/cli/translate.py tests/test_cli.py README.md`
Expected: PASS
