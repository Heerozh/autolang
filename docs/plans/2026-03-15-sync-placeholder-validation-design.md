# Sync Placeholder Validation Design

## Context

`tt sync` currently does two things for locale TOML files:

- add missing source templates as `MISSING_TRANSLATION`
- remove stale entries that no longer exist in source

It does not validate existing translated values. Because locale TOML files are shipped as part of the source distribution and may be edited without careful review, a translated entry can contain an invalid f-string placeholder expression and still survive sync unchanged.

`tt translate` already enforces placeholder compatibility through `validate_translated_text`, but that logic currently lives inside the translate command module instead of a shared location.

## Goals

- Make `tt sync` validate placeholders for existing translated entries.
- Reset invalid translated entries to `MISSING_TRANSLATION` instead of preserving them.
- Count invalid-placeholder resets separately in the sync summary output.
- Reuse one shared placeholder validation implementation for both `tt translate` and `tt sync`.

## Non-Goals

- Changing extraction, cue generation, or locale file discovery.
- Weakening or redefining the current placeholder compatibility rules.
- Adding new placeholder syntax beyond what `tt translate` already allows.

## Approach

### Shared Placeholder Module

Extract placeholder parsing and validation helpers from `src/autolang/cli/translate.py` into a dedicated shared module:

- `src/autolang/cli/placeholders.py`

This module should own:

- placeholder extraction from translated text
- source placeholder normalization
- wrapper compatibility checks for allowed `fmt.*` helpers
- the public `validate_translated_text(source_text, translated_text)` entry point

`src/autolang/cli/translate.py` will import from this module and keep its existing behavior.

### Sync Behavior

When `tt sync` processes an existing locale entry for a source template:

- if the current value is `MISSING_TRANSLATION`, keep it as-is
- otherwise validate it against the source template using the shared validator
- if validation succeeds, keep the translated value
- if validation fails, replace the value with `MISSING_TRANSLATION`

This reset is non-fatal. Sync continues and reports the number of invalid entries that were reset.

### Validation Semantics

The shared validator should preserve current translate-time rules:

- placeholder count must match
- a translated placeholder must match the original expression exactly unless the original expression allows an approved `fmt.*` wrapper
- wrappers must remain within the current allowed candidate set

This means sync catches both classes of bad translation:

- renamed placeholders such as `{other}` for source `{name}`
- semantically incompatible wrappers such as translating a numeric placeholder into `fmt.date(...)`

## Output Changes

Update the sync summary to include a separate reset count. The output shape becomes:

- scanned Python file count
- synced locale file count
- tracked template count
- added missing entry count
- reset invalid placeholder translation count
- removed stale entry count

## Testing

### Shared Validator Coverage

Add or move tests so the shared placeholder validator still covers:

- valid wrappers such as `fmt.currency(price, "USD")`
- invalid renamed placeholders such as `{other}`
- invalid wrapper choices that are syntactically valid but outside the allowed candidates

### Sync Coverage

Add CLI coverage for `tt sync` showing that:

- an existing invalid translation is reset to `MISSING_TRANSLATION`
- the reset count appears in the summary
- valid existing translations remain unchanged

One key regression case should specifically cover a numeric source placeholder whose translation uses an incompatible candidate such as `fmt.date(price)`, which must be reset during sync.

## Risks

- Moving validation helpers out of `translate.py` can accidentally change imports or helper visibility if done too broadly.
- Sync now depends on placeholder validation semantics staying stable; tests need to guard against drift between translate and sync behavior.

## Recommendation

Use a dedicated `placeholders.py` module rather than `common.py`. The logic is domain-specific, already substantial, and likely to be reused by multiple CLI commands.
