# Autolang

`Autolang` automatically adds multilingual support to your Python project, analyzes and
collects context, and uses AI-powered translation so you do not need to maintain or
manage localization manually.

`Autolang` 让你的 Python 项目自动支持多国语言，自动分析并收集信息，外加AI翻译，使你不需要任何维护和管理。

You only need to wrap an f-string like `tt(f"repo stars is {var}K")`, and that is it.

只需要通过 `tt(f"repo stars is {var}K")` 把f-string包装下，就这样。

## Features / 特性

- Fully automatic and maintenance-free
- Supports f-strings, and only f-strings. It uses AST and LSP to record f-string context
  for translation.
- Does not restrict the source language of your text. If your project has collaborators
  from different countries or regions, they can write in their native languages.
- Automatically formats locale-sensitive values such as decimal separators, units, and
  currencies, and provides candidates for AI to handle.

----

- 全自动，免维护
- 支持 f-string，且只允许 f-string。使用AST和LSP，记录f-string上下文用于翻译
- 不限制文本语言，你的项目如果有多个国家地区的合作者，可以让他们使用自己的母语
- 自动格式化，遇到需要本地化的格式，如小数点，单位，货币等，会提供候选让AI处理

## Workflow / 工作流

1. First, wrap all your text with `tt()`.
2. Run `tt init --locales en zh fr` to initialize the languages for your project.
3. Add `tt sycn` and
   `tt translate --model=deepseek-chat --base-url=https://api.deepseek.com/v1 --api-key=sk-xxx`
   to your CI/CD pipeline.

All Done!

----

1. 首先用 `tt()` 包裹你的所有文本。
2. `tt init --locales en zh fr` 来初始化你项目的语言
3. 在 ci/cd 流程中添加 `tt sycn` &&
   `tt translate --model=deepseek-chat --base-url=https://api.deepseek.com/v1 --api-key=sk-xxx`

## Installation / 安装

```bash
uv add autolang && uv add --dev 'autolang[cli]'
```

## Quick Start / 快速开始

```python
from datetime import datetime

import babel
import babel.support

from autolang import install

# locale_str=None means use system language, or an RFC3066 locale like `zh_Hans`
# locale_str=None 表示使用系统语言，或者使用类似 `zh_Hans` 的 RFC3066 locale
translator = install(locale_str=None)
tt = translator.translate

# global localization formatting tool
# 贯穿全局的本地化Format工具
fmt: babel.support.Format = translator.format

name = "Alice"
now = datetime(2026, 3, 11)
follower = 12345
print(tt(f"Hello {name}"))
print(tt(f"Today is {fmt.date(now, format='short')}"))
print(tt(f"Your have {follower / 1000}K followers"))

# currency format
# 货币格式
currency = "CNY"
balance = 864.15
print(tt(f"Balance is {fmt.currency(balance, currency)}"))
```

Execution: / 执行：

```bash
uv run tt init --locales es
uv run tt translate --model=deepseek-chat --base-url=https://api.deepseek.com/v1 --api-key=sk-xx
uv run readme.py
```

Example output: / 示例输出：

```text
Hola Alice
Today is 11/3/26
Tienes 12 mil seguidores
El saldo es 864,15 CNY
```

## Public API / 公共 API

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

----

- `install(locale_dir="locales", locale_str=None)` 创建并返回一个 translator 实例。
- `translator.translate(text)` 翻译当前调用位置的文本。
- `translator.reload()` 重新加载该实例的 locale 文件，并清空缓存的调用位置条目。
- `translator.clear_cache()` 在不重新加载文件的情况下清空实例缓存。

## CLI / 命令行工具

The project also ships a short developer CLI command: `tt`.

项目也提供了一个简短的开发者 CLI 命令：`tt`。

For downstream projects using `uv`, install it with:

对于使用 `uv` 的下游项目，可以这样安装：

```bash
uv add autolang
uv add --dev 'autolang[cli]'
```

The CLI tool depends on the `basedpyright` LSP package, so it is only added to the
development environment.

CLI工具依赖 `basedpyright` LSP包，所以只添加到开发者环境中去。

### Init / 初始化

Initialize locale TOML files.

初始化 locale TOML 文件。

```bash
tt init \
  --source src \
  --locale-dir locales \
  --locales en es
```

By default, the command:

默认情况下，这个命令会：

- scan Python files under `--source`
- create one TOML file for each requested locale
- skip files that already exist
- write all keys as `"text" = "MISSING_TRANSLATION"`

----

- 扫描 `--source` 下的 Python 文件
- 为每个请求的 locale 创建一个 TOML 文件
- 如果文件已存在，则跳过
- 把所有 key 写成 `"text" = "MISSING_TRANSLATION"`

### Sync / 同步

Sync collected templates across existing locale TOML files:

把收集到的模板同步到现有的 locale TOML 文件中：

```bash
tt sync \
  --source src \
  --locale-dir locales
```

By default, the command:

默认情况下，这个命令会：

- scan Python files under `--source`
- extract `tt("...")` and `tt(f"...")` call sites through a Babel-compatible extractor
- skip hidden and cache/build directories such as `.git`, `.venv`, and `__pycache__`
- keep existing translated values for keys that are still present in source
- check whether existing translated text is safe; it must either remain exactly as it
  appears in the source code or be wrapped in `fmt.*()`, otherwise it is reset to
  `MISSING_TRANSLATION`
- write missing keys as `"source" = "MISSING_TRANSLATION"`
- remove stale keys that are no longer collected from source
- run static analysis and write cue files under `.locales_cue/`
- include per-placeholder context such as the nearest assignment, parameter annotation,
  allowed `fmt.*` candidates, and a recommended candidate when confidence is high

----

- 扫描 `--source` 下的 Python 文件
- 通过兼容 Babel 的提取器提取 `tt("...")` 和 `tt(f"...")` 调用位置
- 跳过 `.git`、`.venv` 和 `__pycache__` 等隐藏目录和缓存/构建目录
- 保留源码中仍然存在的 key 对应的现有翻译值
- 检查现有翻译文本是否安全；它必须要么和源码中的内容完全一致，要么被包裹在 `fmt.*()`
  中，否则就重置为 `MISSING_TRANSLATION`
- 将缺失的 key 写成 `"source" = "MISSING_TRANSLATION"`
- 删除那些已经无法从源码中收集到的过期 key
- 运行静态分析，并把 cue 文件写到 `.locales_cue/` 下
- 为每个占位符包含上下文信息，例如最近的赋值、参数注解、允许使用的 `fmt.*`
  候选项，以及在置信度较高时给出的推荐候选项

### Translate / 翻译

Translate all locale TOML files by filling entries still marked as `MISSING_TRANSLATION`
through an OpenAI-compatible API:

通过兼容 OpenAI 的 API，为所有 locale TOML 文件中仍然标记为 `MISSING_TRANSLATION`
的条目补全翻译：

```bash
tt translate \
  --locale-dir locales \
  --model gpt-4.1-mini \
  --api-key "$OPENAI_API_KEY"
```

By default, the command:

默认情况下，这个命令会：

- discover every `*.toml` file under the locale directory as a translation target
- use each TOML key as the source template text
- read cue text from `.<locale-dir>_cue/*.toml` when available
- read optional project instructions from `TT_PROMPT.md` if found under the locale
  directory, source directory, or current working directory, and append them to the
  system prompt
- only translate locale entries whose current value is `MISSING_TRANSLATION`
- send one source key per model request
- validate the returned JSON and placeholders before writing files when they are safe

----

- 把 locale 目录下的每个 `*.toml` 文件都作为翻译目标
- 使用每个 TOML key 作为源模板文本
- 在可用时从 `.<locale-dir>_cue/*.toml` 读取 cue 文本
- 如果在 locale 目录、源码目录或当前工作目录下找到 `TT_PROMPT.md`，就读取其中可选的项目说明并追加到
  system prompt 中
- 只翻译当前值为 `MISSING_TRANSLATION` 的 locale 条目
- 每次模型请求只发送一个源 key
- 在安全的前提下校验返回的 JSON 和占位符后再写入文件

The CLI also reads these environment variables:

CLI 也会读取这些环境变量：

- `TT_API_KEY` or `OPENAI_API_KEY`
- `TT_BASE_URL` or `OPENAI_BASE_URL`
- `TT_MODEL` or `OPENAI_MODEL`

## How It Works / 工作原理

At a high level:

大致流程如下：

1. You call `tt(f"...")`.
   Here `tt = translator.translate`.
2. The library inspects the caller frame and maps it back to the AST node for that exact
   call site.
3. It rebuilds the source template, for example `Hello {name}`.
4. It loads the translated template from TOML.
5. It compiles the translated template as an f-string expression and caches it per
   translator instance.
6. Later calls from the same bytecode location reuse the cached compiled expression.

----

1. 你调用 `tt(f"...")`。
   这里的 `tt = translator.translate`。
2. 库会检查调用者的栈帧，并把它映射回那个精确调用位置对应的 AST 节点。
3. 它会重建源模板，例如 `Hello {name}`。
4. 它会从 TOML 中加载翻译后的模板。
5. 它会把翻译后的模板编译成一个 f-string 表达式，并按 translator 实例进行缓存。
6. 之后来自同一字节码位置的调用会复用这个已缓存的编译表达式。

## Development / 开发

Run tests:

运行测试：

```bash
uv run pytest -q
```

Lint:

代码检查：

```bash
uv run ruff check
```
