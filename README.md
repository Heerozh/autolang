# Autolang

`Autolang` 让你的 Python 项目自动支持多国语言，自动分析并收集信息，外加AI翻译，使你不需要任何维护和管理。
只需要通过 `tt(f"repo stars is {var}K")` 把f-string包装下，就这样。

## 特性

- 全自动，免维护
- 支持 f-string，且只允许 f-string。使用AST和LSP，记录f-string上下文用于翻译
- 不限制文本语言，你的项目如果有多个国家地区的合作者，可以让他们使用自己的母语
- 自动格式化，遇到需要本地化的格式，如小数点，单位，货币等，会提供候选让AI处理

## 工作流

1. 首先用 `tt()` 包裹你的所有文本。
2. `tt init --locales en zh fr` 来初始化你项目的语言
3. 在 ci/cd 流程中添加 `tt sycn` &&
   `tt translate --model=deepseek-chat --base-url=https://api.deepseek.com/v1 --api-key=sk-xxx`

完成！

## Installation

```bash
uv add autolang && uv add --dev 'autolang[cli]'
```

## Quick Start

```python
from datetime import datetime

import babel
import babel.support

from autolang import install

# locale_str=None means use system language, or RFC3066 locale like `zh_Hans`
translator = install(locale_str=None)
tt = translator.translate

# A local fmt object keeps the original f-string valid before translation happens.
fmt: babel.support.Format = translator.format

name = "Alice"
now = datetime(2026, 3, 11)
print(tt(f"Hello {name}"))
print(tt(f"Today is {fmt.date(now, format='short')}"))

# currency format
currency = "CNY"
rate = 7
balance = 123.45 * rate
print(tt(f"Balance is {fmt.currency(balance, currency)}"))


```

Example output:

```text
Hola Alice
Hoy es 11/3/26
El equilibrio es 864,15 CNY
```

## Public API

```python
from autolang import (
    TransparentTranslator,
    install,
)
```

- `install(locale_dir="locales", locale_str=None)` creates and returns a translator
  instance.
- `translator.translate(text)` translates the current call site.
- `translator.reload()` reloads the instance locale file and clears its cached call-site
  entries.
- `translator.clear_cache()` clears the instance cache without reloading files.

## CLI

The project also ships a short developer CLI command: `tt`.
For downstream projects using `uv`, install it with:

```bash
uv add autolang
uv add --dev 'autolang[cli]'
```

CLI工具依赖 `basedpyright` LSP包，所以只添加到开发者环境中去。

### 初始化

Initialize locale TOML files.

```bash
tt init \
  --source src \
  --locale-dir locales \
  --locales en es
```

By default, the command:

- scans Python files under `--source`
- creates one TOML file per requested locale
- if file exists, skip
- writes all keys as `"text" = "MISSING_TRANSLATION"`

### 同步

Sync collected templates across existing locale TOML files:

```bash
tt sync \
  --source src \
  --locale-dir locales
```

By default, the command:

- scans Python files under `--source`
- extracts `tt("...")` and `tt(f"...")` call sites through a Babel-compatible extractor
- skips hidden and cache/build directories such as `.git`, `.venv`, and `__pycache__`
- keeps existing translated values for keys that are still present in source
- check is existing translated text are safe, it must either remain exactly as it
  appears in the source code or be wrapped in `fmt.*()`, if not, reset it to
  `MISSING_TRANSLATION`
- writes missing keys as `"source" = "MISSING_TRANSLATION"`
- removes stale keys that are no longer collected from source
- run static analysis and write cue files under `.locales_cue/`
- includes per-placeholder context such as the nearest assignment, parameter annotation,
  allowed `fmt.*` candidates, and a recommended candidate when confidence is high

### 翻译

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
  directory/source directory/current working directory, and add to system prompt
- only translates locale entries whose current value is `MISSING_TRANSLATION`
- sends one source key per model request
- validates returned JSON and placeholder if safe before writing files

The CLI also reads these environment variables:

- `TT_API_KEY` or `OPENAI_API_KEY`
- `TT_BASE_URL` or `OPENAI_BASE_URL`
- `TT_MODEL` or `OPENAI_MODEL`

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

## Development

Run tests:

```bash
uv run pytest -q
```

Lint:

```bash
uv run ruff check
```

