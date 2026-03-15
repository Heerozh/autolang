# Autolang

`Autolang` is an experimental i18n library for Python `f-string` call sites.
It lets you bind a module-level `tt` function, write `tt(f"...")`, reconstruct the
original template at runtime, look up a translated template from TOML, and re-evaluate
the translated placeholders with Babel-aware formatting.

## Status

This project is under active development.

Stable today:

- `install(locale, locale_dir)` to create an isolated translator instance
- `TransparentTranslator` for explicit instances
- TOML-backed translation lookup
- Babel `fmt.*` placeholder support inside translated templates
- Per-instance call-site cache with `reload()` and `clear_cache()`
- `tt init` and `tt sync` for locale template bootstrapping and synchronization

Planned:

- AI-assisted translation generation
- Better extraction and review workflows

## Installation

```bash
uv add autolang && uv add --dev 'autolang[cli]'
```

## Quick Start

Project layout:

```text
your_app/
  app.py
  locales/
    es.toml
```

`locales/es.toml`

```toml
"Hello {name}" = "Hola {name}"
"Today is {fmt.date(now, format='short')}" = "Hoy es {fmt.date(now, format='short')}"
```

`app.py`

```python
from datetime import datetime

from babel import Locale
from babel.support import Format

from autolang import install

translator = install("es", "locales")
tt = translator.translate

# A local fmt object keeps the original f-string valid before translation happens.
fmt = Format(Locale.parse("en"))

name = "Alice"
now = datetime(2026, 3, 11)

print(tt(f"Hello {name}"))
print(tt(f"Today is {fmt.date(now, format='short')}"))
```

Example output:

```text
Hola Alice
Hoy es 11/3/26
```

## Public API

```python
from autolang import (
    TransparentTranslator,
    install,
)
```

- `install(locale_str, locale_dir="locales")` creates and returns a translator instance.
- `TransparentTranslator(locale_str, locale_dir="locales")` creates an explicit
  translator instance with its own cache.
- `translator.translate(text)` translates the current call site.
- `translator.reload()` reloads the instance locale file and clears its cached call-site
  entries.
- `translator.clear_cache()` clears the instance cache without reloading files.

## Module Setup

The recommended pattern is to initialize a module-level `tt` variable once and then call
`tt(...)` everywhere in that module.

```python
from autolang import install

translator = install("es", "locales")
tt = translator.translate
```

## CLI

The project also ships a short developer CLI command: `tt`.
For downstream projects using `uv`, install it with:

```bash
uv add autolang
uv add --dev 'autolang[cli]'
```

Installing only `autolang` keeps the runtime library available without the optional
`basedpyright` dependency. Adding the `cli` extra enables the richer placeholder
analysis used by the developer tooling.

Translate all locale TOML files by filling entries still marked as `MISSING_TRANSLATION`
through an OpenAI-compatible API:

```bash
tt translate \
  --locale-dir locales \
  --model gpt-4.1-mini \
  --api-key "$OPENAI_API_KEY"
```

By default, the command:

- discovers every `*.toml` file under the locale directory as a translation target
- uses each TOML key as the source template text
- reads cue text from `.<locale-dir>_cue/*.toml` when available
- reads optional project instructions from `tt_prompt.md` if found under the locale
  directory, then the source directory, then the current working directory
- assumes keys may be mixed-language and lets the model decide per item whether
  translation is needed
- only translates locale entries whose current value is `MISSING_TRANSLATION`
- sends one source key per model request and asks the model for every pending target
  locale for that key; independent keys can still execute concurrently
- validates returned JSON and placeholder compatibility before writing files

Useful flags:

- `--overwrite` to force re-translation of existing target values
- `--dry-run` to preview work without writing files
- `--workers 4` to control concurrent batch requests
- `--base-url` to point at any OpenAI-compatible endpoint

The CLI also reads these environment variables:

- `TT_API_KEY` or `OPENAI_API_KEY`
- `TT_BASE_URL` or `OPENAI_BASE_URL`
- `TT_MODEL` or `OPENAI_MODEL`

Initialize locale TOML files from collected `tt(...)` templates:

```bash
tt init \
  --source src \
  --locale-dir locales \
  --locales en es
```

By default, the command:

- scans Python files under `--source`
- extracts `tt("...")` and `tt(f"...")` call sites through a Babel-compatible extractor
- skips hidden and cache/build directories such as `.git`, `.venv`, and `__pycache__`
- creates one TOML file per requested locale
- writes every collected key as `"source" = "MISSING_TRANSLATION"`
- writes static cue entries into matching files under `.locales_cue/`
- includes per-placeholder context such as the nearest assignment, parameter annotation,
  allowed `fmt.*` candidates, and a recommended candidate when confidence is high

Sync collected templates across existing locale TOML files:

```bash
tt sync \
  --source src \
  --locale-dir locales
```

By default, the command:

- scans Python files under `--source`
- requires at least one existing `*.toml` locale file under `--locale-dir`
- keeps existing translated values for keys that are still present in source
- writes missing keys as `"source" = "MISSING_TRANSLATION"`
- removes stale keys that are no longer collected from source
- rewrites cue files under `.locales_cue/` to match the current template set

## How It Works

At a high level:

1. You call `tt(f"...")`.
   Here `tt = translator.translate`.
2. The library inspects the caller frame and maps it back to the AST node for that exact
   call site.
3. It rebuilds the source template, for example `Hello {name}`.
4. It loads the translated template from TOML.
5. It compiles the translated template as an f-string expression and caches it per
   translator instance.
6. Later calls from the same bytecode location reuse the cached compiled expression.

## Constraints

This is not a drop-in replacement for mature gettext tooling yet.

- The main path is designed for direct `tt(f"...")` usage after binding
  `tt = translator.translate`.
- Library code should keep its own translator instance and bind its own `tt` function in
  module scope.
- Translation lookup is currently a flat TOML key-value map.
- Static cue collection writes analysis data into a sibling hidden directory such as
  `.locales_cue`.
- If translated placeholder expressions are invalid or fail at evaluation time, the
  library falls back to the original rendered text.
- The library currently relies on runtime frame inspection and AST recovery, so unusual
  execution environments may behave differently.

## Development

Run tests:

```bash
uv run pytest -q
```

Lint:

```bash
uv run ruff check
```

## Roadmap

- AI-generated translations from source templates and static cues
- Locale file generation and diffing
- Better developer tooling around extraction, validation, and review
