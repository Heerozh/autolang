# Translate Progress Persistence Design

**Goal:** Add visible overall progress to `tt translate` and persist each completed translation batch immediately so interrupted runs keep prior results.

**Architecture:** Keep the existing per-key batch model and hook progress reporting into batch completion. Persist results as each batch finishes instead of accumulating all outcomes in memory for a final write. Preserve fail-fast behavior: if any batch raises, exit immediately without rolling back earlier writes.

**Scope:**
- Show overall translation progress during `tt translate`
- Prefer `tqdm` when available
- Fall back to simple textual progress when `tqdm` is unavailable
- Write each completed batch to locale TOML files immediately unless `--dry-run`
- Stop on first batch failure while retaining already-written results

**Non-goals:**
- Retrying failed batches
- Aggregating multiple failures before exit
- Changing translation prompt semantics
