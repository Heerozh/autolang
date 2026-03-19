# Autolang

`Autolang` 是一个面向 Python `gettext` 工作流的自动翻译 CLI。

它的职责很薄：
- 用 `Babel` 提取源码中的 `_()` 文本并维护 `pot/po`
- 用 OpenAI 兼容接口翻译 `po` 里的未翻译条目
- 按语言和来源文件分批发送给大模型，并把同文件已翻译文本作为参考上下文

当前项目仍在早期阶段，核心命令是 `init`、`sync`、`translate`。

## 工作流

典型流程如下：

1. 在 Python 代码里用 `gettext` 包裹文案。
2. 执行 `autolang init` 初始化语言目录和 `po` 文件。
3. 文案变更后执行 `autolang sync`，让 `po` 跟源码保持同步。
4. 执行 `autolang translate`，把未翻译条目批量发送给大模型补全。

示例源码：

```python
from gettext import gettext as _

print(_("Hello {name}"))
print(_("保存成功"))
```

## 安装

项目使用 `uv` 管理依赖：

```bash
uv sync --dev
```

CLI 入口：

```bash
uv run autolang --help
```

## 命令

### `init`

初始化目标语言的目录结构和 `po` 文件。命令会先调用 `pybabel extract` 生成 `pot`，再对每个语言执行 `pybabel init`。

```bash
uv run autolang init -d locales -l en -l zh --source .
```

常用参数：
- `-d, --directory`: 语言目录，默认 `locales`
- `-l, --locale`: 目标语言，可重复传入
- `--source`: 需要扫描的源码路径，可重复传入

初始化后目录通常类似：

```text
locales/
  messages.pot
  en/LC_MESSAGES/messages.po
  zh/LC_MESSAGES/messages.po
```

### `sync`

同步源码文案到所有语言的 `po` 文件。命令会重新调用 `pybabel extract` 和 `pybabel update`。

```bash
uv run autolang sync -d locales --source .
```

同步行为：
- 源码新增文案：添加到所有语言的 `po`
- 源码删除文案：从所有语言的 `po` 删除
- 已有翻译：保留不变

### `translate`

扫描 `po` 文件中的未翻译文本，按 `语言 + 来源文件` 分组，再按批次发送给大模型。

```bash
uv run autolang translate -d locales --source .
```

也可以显式传模型参数：

```bash
uv run autolang translate \
  -d locales \
  --source . \
  --model gpt-4.1-mini \
  --base-url https://your-openai-compatible-endpoint/v1 \
  --api-key your-api-key
```

翻译行为：
- 只处理当前未翻译的单数条目
- 按来源文件分批，避免把无关文件混在同一次请求里
- 将同语言、同来源文件下已翻译文本作为参考上下文传给模型
- 保留 `{name}`、`%(count)s`、`%s`、代码标识、路径、CLI 参数等技术内容
- 不要求声明源语言，因为 `_()` 里可能是混合语言；模型只需要输出目标语言版本

常用参数：
- `-d, --directory`: 语言目录，默认 `locales`
- `--source`: 来源路径提示，可重复传入
- `--model`: 模型名
- `--base-url`: OpenAI 兼容接口地址
- `--api-key`: 接口密钥
- `--batch-size`: 单次请求最多发送多少条未翻译文本，默认 `50`

## 模型配置

`translate` 支持命令行参数，也支持环境变量。

优先使用命令行参数；未传时回退到以下环境变量：

```bash
export AUTOLANG_MODEL=gpt-4.1-mini
export AUTOLANG_BASE_URL=https://your-openai-compatible-endpoint/v1
export AUTOLANG_API_KEY=your-api-key
```

也兼容以下变量名：

```bash
export OPENAI_MODEL=gpt-4.1-mini
export OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
export OPENAI_API_KEY=your-api-key
```

## Domain 配置

项目对用户侧隐藏了 gettext domain，不再通过 CLI 传 `-D/--domain`。

内部统一从 `DEFAULT_DOMAIN` 环境变量读取；未设置时默认使用 `messages`。

```bash
export DEFAULT_DOMAIN=messages
```

如果你确实需要另一套 catalog 文件名，可以在执行命令前临时切换：

```bash
DEFAULT_DOMAIN=backend uv run autolang init -d locales -l zh --source .
```

## 自定义提示词

`translate` 会自动查找 `-d` 目录下的 `PROMPT.md`。

例如：

```text
locales/
  PROMPT.md
  messages.pot
  zh/LC_MESSAGES/messages.po
```

如果文件存在，其内容会作为额外系统提示词附加到默认翻译提示词后面。这个文件适合放项目术语表、品牌名约束、语气风格要求等。

示例：

```md
## Project-specific terminology

- `Autolang` is the project name. Do not translate or localize `Autolang`.
- Keep CLI flags such as `--source` unchanged.
- Prefer concise product UI wording.
```

## 当前限制

当前实现有这些边界：
- 目前只处理单数条目，不处理 `msgid_plural`
- 默认直接回写 `po` 文件，尚未实现重试、并发控制和断点恢复
- `sync` 和 `init` 只是调用 `Babel`，不自定义提取或合并逻辑

## 开发

运行测试：

```bash
uv run pytest -q
```

当前测试覆盖：
- `init` 初始化多语言目录
- `sync` 对新增、删除、已存在翻译的处理
- `translate` 的分组、参考译文透传、`PROMPT.md` 注入和回写逻辑
