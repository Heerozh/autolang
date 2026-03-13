# Autolang

`Autolang` is an experimental i18n library for Python `f-string` call sites.
It lets you bind a module-level `tt` function, write `tt(f"...")`, reconstruct the original template at runtime, look up a translated template from TOML, and re-evaluate the translated placeholders with Babel-aware formatting.

## Status

This project is under active development.

Stable today:
- `install(locale, locale_dir)` to create an isolated translator instance
- `TransparentTranslator` for explicit instances
- TOML-backed translation lookup
- Babel `fmt.*` placeholder support inside translated templates
- Per-instance call-site cache with `reload()` and `clear_cache()`
- Optional runtime collection of missing strings into TOML

Planned:
- AI-assisted translation generation
- Automatic TOML comparison and sync tools
- Better extraction and review workflows

## Installation

```bash
pip install autolang
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

- `install(locale_str, locale_dir="locales", collect_missing=False, collect_locales=None)` creates and returns a translator instance.
- `TransparentTranslator(locale_str, locale_dir="locales", collect_missing=False, collect_locales=None)` creates an explicit translator instance with its own cache.
- `translator.translate(text)` translates the current call site.
- `translator.collect(text, cue=None)` records a runtime string into the configured collection TOML and returns the original text.
- `translator.reload()` reloads the instance locale file and clears its cached call-site entries.
- `translator.clear_cache()` clears the instance cache without reloading files.

## Module Setup

The recommended pattern is to initialize a module-level `tt` variable once and then call `tt(...)` everywhere in that module.

```python
from autolang import install

translator = install("es", "locales")
tt = translator.translate
```

If you also want runtime collection helpers in the same module:

```python
from autolang import install

translator = install("es", "locales", collect_missing=True, collect_locales=["en", "es"])
tt = translator.translate
collect = translator.collect
```

## Runtime Collection

If you want untranslated text to be collected while the program runs, enable `collect_missing` on your own translator instance.

```python
from autolang import install

translator = install("es", "locales", collect_missing=True, collect_locales=["en", "es", "fr"])
tt = translator.translate

name = "Alice"
print(tt(f"Hello {name}"))
translator.collect("background worker started")
```

This writes missing entries directly into each configured translation table:

```toml
"Hello {name}" = "Hello {name}"
"background worker started" = "background worker started"
```

For the example above, the library writes the same placeholder entries into:
- `locales/en.toml`
- `locales/es.toml`
- `locales/fr.toml`

It also writes the runtime rendered result for each key into parallel cue files:
- `.locales_cue/en.toml`
- `.locales_cue/es.toml`
- `.locales_cue/fr.toml`

Example cue file:

```toml
"Hello {name}" = "Hello Alice"
"background worker started" = "background worker started"
```

## CLI

The project also ships a short developer CLI command: `tt`.

Translate all target locale TOML files from a source locale file through an OpenAI-compatible API:

```bash
tt translate \
  --locale-dir locales \
  --source-locale en \
  --model gpt-4.1-mini \
  --api-key "$OPENAI_API_KEY"
```

By default, the command:
- reads `locales/en.toml` as the source table
- reads `.locales_cue/en.toml` as rendered-example cues when available
- discovers every other `*.toml` file under the same directory as a target locale
- only translates entries that are missing or still equal to the source text
- sends translation requests in batches and can execute multiple batches concurrently
- validates returned JSON and placeholder compatibility before writing files

Useful flags:
- `--target-locales es fr` to restrict which locale files are updated
- `--overwrite` to force re-translation of existing target values
- `--dry-run` to preview work without writing files
- `--batch-size 20` to control how many entries are sent in one model request
- `--workers 4` to control concurrent batch requests
- `--base-url` to point at any OpenAI-compatible endpoint

The CLI also reads these environment variables:
- `TT_API_KEY` or `OPENAI_API_KEY`
- `TT_BASE_URL` or `OPENAI_BASE_URL`
- `TT_MODEL` or `OPENAI_MODEL`

## How It Works

At a high level:

1. You call `tt(f"...")`.
   Here `tt = translator.translate`.
2. The library inspects the caller frame and maps it back to the AST node for that exact call site.
3. It rebuilds the source template, for example `Hello {name}`.
4. It loads the translated template from TOML.
5. It compiles the translated template as an f-string expression and caches it per translator instance.
6. Later calls from the same bytecode location reuse the cached compiled expression.

## Constraints

This is not a drop-in replacement for mature gettext tooling yet.

- The main path is designed for direct `tt(f"...")` usage after binding `tt = translator.translate`.
- Library code should keep its own translator instance and bind its own `tt` function in module scope.
- Translation lookup is currently a flat TOML key-value map.
- Runtime collection writes flat TOML entries and currently rewrites the file content instead of preserving comments.
- Runtime collection writes directly into the language TOML files you configure in `collect_locales`.
- Runtime cue collection writes rendered examples into a sibling hidden directory such as `.locales_cue`.
- If translated placeholder expressions are invalid or fail at evaluation time, the library falls back to the original rendered text.
- The library currently relies on runtime frame inspection and AST recovery, so unusual execution environments may behave differently.

## Development

Run tests:

```bash
uv run pytest -q
```

## Roadmap

- AI-generated translations from source templates and rendered examples
- Locale file generation and diffing
- Better developer tooling around extraction, validation, and review
