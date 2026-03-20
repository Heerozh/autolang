# Autolang

Autolang provides fully automatic, maintenance-free multilingual support for Python projects. It analyzes and collects context, then sends it to an LLM for translation.

Autolang 为 Python 项目提供全自动、免维护的多语言支持。它会分析并收集上下文，然后发送给大模型进行翻译。

It does not restrict the source language of your text. If your project has collaborators from different countries or regions, they can write in their native languages.

它不限制文本的源语言。如果你的项目有来自不同国家或地区的协作者，他们可以直接使用自己的母语编写内容。

## Workflow / 工作流

Its responsibility is intentionally narrow:

它的职责刻意保持得很薄：

- Extract `_()` strings from source code with `Babel` and maintain `pot/po` files, which are GNU-standard localization files.
- Translate untranslated entries in `po` files through an OpenAI-compatible API, while using code comments and already translated text from the same file as reference context.
- Compile the results into binary `mo` files at the end.

----

- 用 `Babel` 提取源码中的 `_()` 文本并维护 `pot/po` 文件，这些文件是 GNU 标准的多语言文件。
- 通过 OpenAI 兼容接口翻译 `po` 文件中的未翻译条目，并把代码注释、同一文件中已经翻译的文本作为参考上下文。
- 最后将结果编译为二进制 `mo` 文件。

A typical flow looks like this:

典型流程如下：

1. Wrap user-facing text with `gettext` in Python code.
2. Run `autolang init` to initialize the locale directory and `po` files.
3. Run `autolang sync` and `autolang translate` in your CI/CD workflow to keep `po` files synchronized with source code and let the LLM fill in missing translations.

----

1. 在 Python 代码里用 `gettext` 包裹面向用户的文案。
2. 执行 `autolang init` 初始化语言目录和 `po` 文件。
3. 在 CI/CD 工作流中执行 `autolang sync` 和 `autolang translate`，让 `po` 文件与源码保持同步，并交给大模型补全缺失翻译。

Example source code:

示例源码：

```python
from gettext

# i18n.py for setting up the translator / i18n.py，用于设置翻译器
def get_system_language() -> str:
    if sys.platform == "win32":
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(lang_id)
    else:
        return locale.getlocale()

translator = gettext.translation(
            "messages",
            localedir="i18n",
            languages=[get_system_language(), "en"],
            fallback=True,
        )
_ = translator.gettext

# Your application code / 你的应用代码
print(_("Hello {name}").format(name="alice"))
print(_("保存成功"))
```

## Installation / 安装

Just add it to your development dependencies:

只需将它加入开发依赖：

```bash
uv add --dev autolang
```

CLI entry point:

CLI 入口：

```bash
uv run autolang --help
```

## Commands / 命令

### `init`

Initialize the directory structure and `po` files for the target locales. The command first runs `pybabel extract` to generate a `pot` file, then runs `pybabel init` for each locale.

初始化目标语言的目录结构和 `po` 文件。命令会先调用 `pybabel extract` 生成 `pot` 文件，再对每个语言执行 `pybabel init`。

```bash
uv run autolang init -d i18n -l en -l zh --source ./src
```

Common arguments:

常用参数：

- `-d, --directory`: Locale directory. Default: `i18n`
- `-l, --locale`: Target locale. Can be passed multiple times
- `--source`: Source code path to scan. Can be passed multiple times

----

- `-d, --directory`: 语言目录，默认 `i18n`
- `-l, --locale`: 目标语言，可重复传入
- `--source`: 需要扫描的源码路径，可重复传入

After initialization, the directory usually looks like this:

初始化后目录通常类似：

```text
i18n/
  messages.pot
  en/LC_MESSAGES/messages.po
  zh/LC_MESSAGES/messages.po
```

### `sync`

Synchronize source strings into the `po` files for all locales. The command reruns `pybabel extract` and `pybabel update`.

将源码文案同步到所有语言的 `po` 文件。命令会重新调用 `pybabel extract` 和 `pybabel update`。

```bash
uv run autolang sync -d i18n --source ./src
```

Synchronization behavior:

同步行为：

- Newly added source strings: added to the `po` files for all locales
- Removed source strings: deleted from the `po` files for all locales
- Existing translations: kept unchanged

----

- 源码新增文案：添加到所有语言的 `po` 文件
- 源码删除文案：从所有语言的 `po` 文件删除
- 已有翻译：保持不变

Tagged translator comments placed immediately above gettext calls are also extracted into PO context during `init` and `sync`. Supported tags include `NOTE`, `NOTES`, `TRANSLATOR`, `TRANSLATORS`, `I18N`, `L10N`, `LOCALIZATION`, and `LOC`.

紧贴在 gettext 调用上方的带标签翻译注释，也会在 `init` 和 `sync` 期间被提取到 PO 上下文中。当前支持的标签包括 `NOTE`、`NOTES`、`TRANSLATOR`、`TRANSLATORS`、`I18N`、`L10N`、`LOCALIZATION` 和 `LOC`。

### `translate`

Scan untranslated text in `po` files, group entries by `locale + source file`, and then send them to the LLM in batches.

扫描 `po` 文件中的未翻译文本，按“语言 + 来源文件”分组，然后分批发送给大模型。

```bash
uv run autolang translate -d i18n --source ./src
```

You can also pass model settings explicitly:

也可以显式传入模型参数：

```bash
uv run autolang translate \
  -d i18n \
  --source ./src \
  --model deepseek-chat \
  --base-url https://api.deepseek.com \
  --api-key your-api-key
```

Translation behavior:

翻译行为：

- Process currently untranslated singular and plural entries
- Batch by source file to avoid mixing unrelated files in the same request
- Send already translated text from the same locale and source file as reference context
- Preserve technical content such as `{name}`, `%(count)s`, `%s`, code identifiers, paths, and CLI arguments
- No source language declaration is required, because text inside `_()` may be mixed-language; the model only needs to output the target-language version

----

- 处理当前未翻译的单数和复数条目
- 按来源文件分批，避免在同一次请求中混入无关文件
- 将同语言、同来源文件下已翻译的文本作为参考上下文传给模型
- 保留 `{name}`、`%(count)s`、`%s`、代码标识符、路径、CLI 参数等技术内容
- 不要求声明源语言，因为 `_()` 里的文本可能是混合语言；模型只需要输出目标语言版本

Common arguments:

常用参数：

- `-d, --directory`: Locale directory. Default: `locales`
- `--source`: Source-path hints. Can be passed multiple times
- `--model`: Model name
- `--base-url`: OpenAI-compatible API base URL
- `--api-key`: API key
- `--batch-size`: Maximum number of untranslated strings per request. Default: `50`

----

- `-d, --directory`: 语言目录，默认 `locales`
- `--source`: 来源路径提示，可重复传入
- `--model`: 模型名
- `--base-url`: OpenAI 兼容接口地址
- `--api-key`: 接口密钥
- `--batch-size`: 单次请求最多发送多少条未翻译文本，默认 `50`

## Model Configuration / 模型配置

`translate` supports both command-line arguments and environment variables.

`translate` 同时支持命令行参数和环境变量。

Command-line arguments take priority. If they are not provided, Autolang falls back to the following environment variables:

命令行参数优先；如果未传入，则会回退到以下环境变量：

```bash
export AUTOLANG_MODEL=gpt-4.1-mini
export AUTOLANG_BASE_URL=https://your-openai-compatible-endpoint/v1
export AUTOLANG_API_KEY=your-api-key
```

The following variable names are also supported:

也兼容以下变量名：

```bash
export OPENAI_MODEL=gpt-4.1-mini
export OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
export OPENAI_API_KEY=your-api-key
```

## Domain Configuration / Domain 配置

The project hides the gettext domain from end users, so `-D/--domain` is no longer exposed through the CLI.

项目对用户侧隐藏了 gettext domain，因此不再通过 CLI 暴露 `-D/--domain`。

Internally, it always reads from the `DEFAULT_DOMAIN` environment variable. If it is not set, `messages` is used by default.

内部统一从 `DEFAULT_DOMAIN` 环境变量读取；如果未设置，默认使用 `messages`。

```bash
export DEFAULT_DOMAIN=messages
```

If you really need another catalog filename, you can switch temporarily before running a command:

如果你确实需要另一套 catalog 文件名，可以在执行命令前临时切换：

```bash
DEFAULT_DOMAIN=backend uv run autolang init -d locales -l zh --source .
```

## Custom Prompt / 自定义提示词

`translate` automatically looks for `PROMPT.md` under the directory passed to `-d`.

`translate` 会自动查找 `-d` 目录下的 `PROMPT.md`。

For example:

例如：

```text
i18n/
  PROMPT.md
  messages.pot
  zh/LC_MESSAGES/messages.po
```

If the file exists, its content is appended to the default translation system prompt as additional instructions. This file is a good place for project glossaries, brand-name constraints, tone requirements, and similar guidance.

如果该文件存在，它的内容会作为额外说明追加到默认翻译系统提示词之后。这个文件适合放项目术语表、品牌名约束、语气风格要求等内容。

Example:

示例：

```md
## Project-specific terminology

- `Autolang` is the project name. Do not translate or localize `Autolang`.
- Keep CLI flags such as `--source` unchanged.
- Prefer concise product UI wording.
```
