# Per-Key Multi-Locale Translate Design

## Context

`tt translate` currently builds pending work per target locale and sends batches that contain multiple source keys for one locale. That means the same source key and its cue are repeated once per missing locale. When cues are large and several locale files are missing the same entry, request context grows linearly with the number of locales.

The requested behavior is the inverse batching model: send one source key at a time and ask the model to return translations for every target locale that still needs that key. This keeps each request focused on a single source template while avoiding repeated cue text.

## Goals

- Change model requests from `many keys -> one locale` to `one key -> many locales`.
- Preserve existing placeholder validation guarantees for every translated locale.
- Keep CLI usage stable for existing callers.
- Continue supporting concurrent requests across independent source keys.

## Non-Goals

- Changing sync/init behavior.
- Introducing persistent caching or translation memory.
- Redesigning CLI flags beyond preserving compatibility.

## Approach

### Request Model

Replace the current batch request shape with a per-key request containing:

- The source key text.
- Its static-analysis cue.
- A list of target locales and target language display names that still need translation.

The prompt will instruct the model to translate the single source template for every requested locale and return JSON keyed by locale.

### Response Model

Parse one response object that contains one translation record per requested locale. Each record will still carry:

- `locale`
- `text`
- `needs_review`
- `issues`

Each returned text is validated with the existing placeholder validator against the same source key.

### Scheduling

Build pending work by source key instead of by locale:

- Scan all locale TOML files.
- For each key, gather the locales whose current value is `MISSING_TRANSLATION` or should be overwritten.
- Create one request per key only when at least one target locale is pending.

Thread-pool concurrency remains useful because requests for different keys are independent.

### Writeback

After each per-key outcome is validated, write each locale-specific translation back into that locale's in-memory table, then persist the TOML files as before.

### CLI Compatibility

Keep the `translate` CLI signature intact. `--workers` still controls concurrency across keys. `--batch-size` will remain accepted for compatibility, but the request path will operate per key regardless of its value.

## Error Handling

- Missing locales in the response remain a hard error.
- Unknown locales in the response remain a hard error.
- Invalid placeholder rewrites for any locale remain a hard error.
- Existing cue-file preconditions remain unchanged.

## Testing

Add CLI tests covering:

- One request per source key with multiple target locales in the same request.
- Correct writeback into multiple locale files from one response.
- Placeholder validation for locale-scoped response items.
- Prompt text that clearly describes single-key, multi-locale translation.
