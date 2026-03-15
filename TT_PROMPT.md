## Project-specific terminology

- `Autolang` is the project name. Do not translate or localize `Autolang`.
- `tt` is the project's translation helper function name. Do not translate, expand, or reinterpret `tt`.
- `TransparentTranslator` is a Python class name. Keep it unchanged.
- `install` may refer to the project's API entry point `autolang.install(...)`, not necessarily a user-facing "install" action.

## Translation context

- A `source template` is the original Python template string reconstructed from a `tt(...)` call site. It is internal technical context, not a product label.
- A `locale file` is a TOML translation file such as `en.toml` or `fr.toml`.
- A `cue` is static-analysis context attached to a source template. It helps disambiguate meaning, placeholder types, and formatting intent. It is not user-visible text and should not be translated into the final output.
- `MISSING_TRANSLATION` is an internal sentinel meaning "not translated yet". Never copy or translate `MISSING_TRANSLATION` into the output text.

## Placeholder and formatting terminology

- A `placeholder` means a Python template placeholder like `{name}` or `{fmt.date(now)}`.
- `fmt.*` refers to Babel-aware formatting helpers such as `fmt.date`, `fmt.currency`, and `fmt.percent`. Treat these as technical formatting functions, not normal words.
- If a source string contains placeholders or `fmt.*` helpers, preserve their technical structure exactly according to the hard rules in the main system prompt.

## Naming guidance

- When a key contains technical identifiers such as `Autolang`, `tt`, `TransparentTranslator`, `fmt`, `TOML`, `Python`, or API/class/function names, assume they are technical terms and usually should stay unchanged unless the surrounding natural-language sentence clearly requires otherwise.
- When the source looks like developer tooling text, CLI help text, diagnostics, or documentation, prefer technically precise wording over marketing language.
