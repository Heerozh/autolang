# Repository Guidelines

## Project Structure & Module Organization
Core library code lives in `src/transparentlation/`. `translator.py` contains the runtime translation logic and public helpers are re-exported from `src/transparentlation/__init__.py`. Tests live in `tests/`, with functional coverage in `test_core.py`, API checks in `test_public_api.py`, and performance checks in `test_benchmark.py`. Sample locale data is stored in `tests/locales/`. 

## Build, Test, and Development Commands
Use `uv` for local development.

- `uv sync --dev` installs runtime and development dependencies from `pyproject.toml`.
- `uv run pytest -q` runs the full test suite, including benchmark tests.
- `uv run pytest tests/test_core.py -q` runs a focused subset while iterating.
- `uv run pyright` runs static type checking using the repository's `standard` mode setting.
- `uv run ruff` for code style check.
- `uv build` builds a distributable package when you need to validate packaging metadata.

## Coding Style & Naming Conventions
Target Python 3.11+ and follow existing style in `src/transparentlation/translator.py`: 4-space indentation, snake_case for functions and variables, PascalCase for classes, and explicit type hints on public APIs. Keep modules small and standard-library-first where practical. Prefer dataclasses and narrow helper functions over large stateful blocks. Avoid editing generated artifacts such as `src/transparentlation.egg-info/` and `__pycache__/`.

## Testing Guidelines
Add tests beside related behavior under `tests/` using `test_*.py` filenames and `test_*` function names. Favor small functional tests for translation behavior and fallback cases; use `tmp_path` for locale-file mutations. Benchmark coverage uses `pytest-benchmark`, so performance-sensitive changes should preserve or update the relevant benchmark assertions. Run `uv run pytest -q` before opening a PR.

## Commit & Pull Request Guidelines
This repository currently has no commit history on `main`, so there is no established convention to copy. Use short, imperative commit subjects such as `Add cache invalidation test` or `Refine TOML reload fallback`. Pull requests should include a brief problem statement, a summary of behavior changes, test evidence (`uv run pytest -q`), and sample output or screenshots only if user-facing docs changed.
