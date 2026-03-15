from __future__ import annotations

import argparse
import ast
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from ..toml_io import load_string_table, write_string_table
from .common import (
    MISSING_TRANSLATION,
    build_cue_dir_path,
    build_source_cue_path,
    list_locale_files,
    load_shared_cues,
    locale_display_name,
    normalize_locale_name,
    resolve_locale_dir_from_source,
)
from .i18n import tt

TRANSLATION_PROMPT_FILE_NAME = "TT_PROMPT.md"
TRANSLATION_SYSTEM_PROMPT = """You are a localization rewrite engine for python template strings with Babel CLDR formatting.

Task:
-----
Rewrite the single source template for each requested target locale, while preserving placeholders.
You may wrap placeholders with a limited set of Babe formatting helpers (in Allowed candidates) 
when the source template and the Cue strongly imply locale-aware formatting. 

Source entries can contain mixed languages.
For each requested locale, first determine whether the source already reads naturally for that locale. 
If it already fits the target locale, keep it unchanged.
If it does not fit the target locale, translate or adapt it for that locale.

Output format:
--------------
Return JSON only:
{
  "translations": [
    {
      "locale": "es",
      "text": "...",
      "needs_review": false,
      "issues": []
    }
  ]
}

Hard rules:
-----------
1. Preserve the number of placeholders.
2. Never rename, invent, or delete placeholders.
3. Only change a placeholder by keeping it unchanged or wrapping the original expression with one allowed fmt helper.
4. If the source template already contains an allowed fmt helper, keep that placeholder expression exactly.
5. Do not output arbitrary code, indexing, attribute access, or method calls other than allowed fmt helpers.
6. If the cue strongly indicates date, time, datetime, currency, percent, compact number, or timedelta formatting, you may apply the matching fmt helper.
7. If the cue includes allowed candidates, stay within those candidates unless the source already uses an allowed fmt helper.
8. If the cue is weak or ambiguous, keep the placeholder unchanged.
9. If the text is already appropriate for the target locale, return it unchanged.
10. Return one translation for every requested locale.
11. Do not explain your reasoning.
12. Return JSON only.

Example Input A:
--------------
Source template:
project reached {stars}K stars

Cue:
Location: xxxx.py:123
Placeholder: {stars}
Expression: stars
Definition: stars = db.starts
Annotation: int
Allowed candidates: {stars}, {fmt.decimal(stars)}, {fmt.number(stars)}, {fmt.currency(stars, \"USD\")}, {fmt.compact_decimal(stars)}, {fmt.compact_currency(stars, \"USD\")}, {fmt.compact_decimal(stars * 1000)}, {fmt.compact_decimal(stars * 1000000)}, {fmt.compact_decimal(stars * 1000000000)}, {fmt.compact_currency(stars * 1000, \"USD\")}, {fmt.compact_currency(stars * 1000000, \"USD\")}, {fmt.compact_currency(stars * 1000000000, \"USD\")}, {fmt.percent(stars)}, {fmt.percent(stars / 100)}, {fmt.timedelta(stars)}
Recommended: {stars}
Confidence: low
Notes: Static information identifies this placeholder as numeric, so date/time wrappers were pruned.

Target locales:
- en (English)
- zh (Chinese)


Example Output A:
---------------
{
  "translations": [
    {
      "locale": "en",
      "text": "project reached {stars}K stars",
      "needs_review": false,
      "issues": []
    },
    {
      "locale": "zh",
      "text": "项目达到了{fmt.compact_decimal(stars * 1000)}星",
      "needs_review": false,
      "issues": []
    }
  ]
}

Note for A:
-----------
The unit 'K' is tied to linguistic conventions, and the set of "allowed candidates" 
includes `compact_decimal`; therefore, we convert it back to its original numerical 
value and use `fmt` to compact it once again, and remove K Unit for other language.

"""

PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)}")
ALLOWED_FMT_FUNCS = {
    "date",
    "time",
    "datetime",
    "decimal",
    "number",
    "currency",
    "compact_decimal",
    "compact_currency",
    "percent",
    "timedelta",
}
COMPACT_SCALE_VALUES = {1000, 1000000, 1000000000}


@dataclass(frozen=True, slots=True)
class TranslationTask:
    key: str
    source_text: str
    cue_text: str
    target_locale: str
    target_language: str


@dataclass(frozen=True, slots=True)
class BatchTranslationTarget:
    locale: str
    target_language: str


@dataclass(frozen=True, slots=True)
class BatchTranslationRequest:
    key: str
    source_text: str
    cue_text: str
    targets: tuple[BatchTranslationTarget, ...]


@dataclass(frozen=True, slots=True)
class TranslationResult:
    locale: str
    text: str
    needs_review: bool = False
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchTranslationOutcome:
    key: str
    results: tuple[TranslationResult, ...]


@dataclass(frozen=True, slots=True)
class PlaceholderSpec:
    source_expression: str
    normalized_expression: str
    requires_exact_match: bool


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        extra_system_prompt: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.extra_system_prompt = extra_system_prompt

    def translate_batch(
        self, request: BatchTranslationRequest
    ) -> dict[str, TranslationResult]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": build_chat_messages(
                request, extra_system_prompt=self.extra_system_prompt
            ),
            "response_format": {"type": "json_object"},
        }
        response = self._post_json("/chat/completions", payload)
        content = self._extract_content(response)
        return parse_batch_response(content, request)

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network error path
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API request failed with {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network error path
            raise RuntimeError(f"API request failed: {exc.reason}") from exc

    @staticmethod
    def _extract_content(response: dict[str, object]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"Unexpected API response: {response}")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError(f"Unexpected API response: {response}")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError(f"Unexpected API response: {response}")

        content = message.get("content")
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            if text_parts:
                return "".join(text_parts)

        raise RuntimeError(f"Unexpected API response: {response}")


def handle_translate_command(
    args: argparse.Namespace,
    *,
    client_class: type[OpenAICompatibleClient] = OpenAICompatibleClient,
) -> int:
    source_path = Path(args.source)
    locale_dir_arg = Path(args.locale_dir)
    locale_dir = resolve_locale_dir_from_source(source_path, locale_dir_arg)
    locale_files = list_locale_files(locale_dir)
    if not locale_files:
        raise SystemExit(tt(f"No locale TOML files found in {locale_dir}"))
    ensure_translate_cues_exist(source_path, locale_dir, locale_files)

    source_entries: dict[str, str] = {}
    for locale_path in locale_files:
        for key in load_string_table(str(locale_path)):
            source_entries[key] = key
    if not source_entries:
        raise SystemExit(tt(f"No translatable template keys found in {locale_dir}."))

    model = args.model or os.environ.get("TT_MODEL") or os.environ.get("OPENAI_MODEL")
    if not model:
        raise SystemExit(
            tt("Missing model. Pass --model or set TT_MODEL/OPENAI_MODEL.")
        )

    api_key = (
        args.api_key or os.environ.get("TT_API_KEY") or os.environ.get("OPENAI_API_KEY")
    )
    if not api_key:
        raise SystemExit(
            tt("Missing API key. Pass --api-key or set TT_API_KEY/OPENAI_API_KEY.")
        )

    base_url = (
        args.base_url
        or os.environ.get("TT_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
    )
    if not base_url:
        base_url = "https://api.openai.com/v1"

    workers = max(1, args.workers)

    client = client_class(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=args.timeout,
        extra_system_prompt=load_translation_prompt(source_path, locale_dir),
    )

    target_locales = [normalize_locale_name(path.stem) for path in locale_files]
    source_cues = load_shared_cues(locale_dir)
    target_entries_by_locale: dict[str, dict[str, str]] = {}

    for target_locale in target_locales:
        target_path = locale_dir / f"{target_locale}.toml"
        target_entries_by_locale[target_locale] = load_string_table(str(target_path))

    pending_by_key = build_translation_tasks(
        source_entries=source_entries,
        source_cues=source_cues,
        target_locales=target_locales,
        overwrite=args.overwrite,
        current_entries_by_locale=target_entries_by_locale,
    )

    if not pending_by_key:
        print(
            tt(
                f"Updated {len(target_locales)} locale file(s), translated 0 entry/entries."
            )
        )
        return 0

    total_translated = 0
    progress = create_translation_progress(len(pending_by_key))
    try:
        for outcome in iter_translation_batches(
            client=client,
            pending_by_key=pending_by_key,
            workers=workers,
        ):
            touched_locales: set[str] = set()
            for result in outcome.results:
                target_entries_by_locale[result.locale][outcome.key] = result.text
                total_translated += 1
                touched_locales.add(result.locale)

            if not args.dry_run:
                for target_locale in touched_locales:
                    write_string_table(
                        str(locale_dir / f"{target_locale}.toml"),
                        target_entries_by_locale[target_locale],
                    )
            progress.update()
    finally:
        progress.close()

    print(
        tt(
            f"Updated {len(target_locales)} locale file(s), translated {total_translated} entry/entries."
        )
    )
    return 0


def ensure_translate_cues_exist(
    source_path: Path, locale_dir: Path, locale_files: list[Path]
) -> None:
    cue_dir = build_cue_dir_path(locale_dir)
    cue_files = [path for path in sorted(cue_dir.glob("*.toml")) if path.is_file()]
    if not cue_files:
        raise SystemExit(build_missing_cue_error(source_path, locale_dir))

    missing_cue_paths = [
        build_source_cue_path(locale_dir, locale_path.stem)
        for locale_path in locale_files
        if not build_source_cue_path(locale_dir, locale_path.stem).is_file()
    ]
    if missing_cue_paths:
        raise SystemExit(build_missing_cue_error(source_path, locale_dir))


def build_missing_cue_error(source_path: Path, locale_dir: Path) -> str:
    return tt(
        f"Missing cue TOML files for {locale_dir}. "
        f"Run `tt sync --source {source_path} --locale-dir {locale_dir}` first."
    )


def build_translation_tasks(
    *,
    source_entries: dict[str, str],
    source_cues: dict[str, str],
    target_locales: list[str],
    overwrite: bool,
    current_entries_by_locale: dict[str, dict[str, str]],
) -> dict[str, list[TranslationTask]]:
    pending_by_key: dict[str, list[TranslationTask]] = {}
    for key in source_entries:
        pending_targets: list[TranslationTask] = []
        for target_locale in target_locales:
            current_text = current_entries_by_locale[target_locale].get(key)
            if not should_translate_entry(current_text, overwrite):
                continue
            pending_targets.append(
                TranslationTask(
                    key=key,
                    source_text=key,
                    cue_text=source_cues.get(key, ""),
                    target_locale=target_locale,
                    target_language=locale_display_name(target_locale),
                )
            )
        if pending_targets:
            pending_by_key[key] = pending_targets

    return pending_by_key


def iter_translation_batches(
    *,
    client: OpenAICompatibleClient,
    pending_by_key: dict[str, list[TranslationTask]],
    workers: int,
) -> Iterator[BatchTranslationOutcome]:
    batch_requests = [
        BatchTranslationRequest(
            key=key,
            source_text=tasks[0].source_text,
            cue_text=tasks[0].cue_text,
            targets=tuple(
                BatchTranslationTarget(
                    locale=task.target_locale,
                    target_language=task.target_language,
                )
                for task in tasks
            ),
        )
        for key, tasks in pending_by_key.items()
    ]

    if workers == 1 or len(batch_requests) == 1:
        for batch_request in batch_requests:
            results = validate_batch_results(
                batch_request, client.translate_batch(batch_request)
            )
            yield BatchTranslationOutcome(
                key=batch_request.key,
                results=tuple(
                    results[target.locale] for target in batch_request.targets
                ),
            )
        return

    executor = ThreadPoolExecutor(max_workers=workers)
    future_map = {}
    try:
        future_map = {
            executor.submit(client.translate_batch, batch_request): batch_request
            for batch_request in batch_requests
        }
        for future in as_completed(future_map):
            batch_request = future_map[future]
            results = validate_batch_results(batch_request, future.result())
            yield BatchTranslationOutcome(
                key=batch_request.key,
                results=tuple(
                    results[target.locale] for target in batch_request.targets
                ),
            )
    except Exception:
        for future in future_map:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def create_translation_progress(total: int):
    return tqdm(total=total, desc="Translating", unit="batch")


def validate_batch_results(
    request: BatchTranslationRequest,
    results: dict[str, TranslationResult],
) -> dict[str, TranslationResult]:
    expected_locales = {target.locale for target in request.targets}
    if set(results) != expected_locales:
        raise RuntimeError(
            "Batch result locales do not match request locales. "
            f"expected={sorted(expected_locales)} got={sorted(results)}"
        )

    for result in results.values():
        validate_translated_text(request.source_text, result.text)

    return results


def build_batch_user_prompt(request: BatchTranslationRequest) -> str:
    lines = [
        "Important: source entries come from TOML keys and may be mixed-language. Decide per locale whether translation is needed.",
        "",
        "Translate the single source template below for every target locale.",
        "",
        "Source template:",
        request.source_text,
        "",
        "Cue:",
        request.cue_text or "No additional cue.",
        "",
        "Target locales:",
        "",
    ]

    for target in request.targets:
        lines.append(f"- {target.locale} ({target.target_language})")

    return "\n".join(lines)


def build_chat_messages(
    request: BatchTranslationRequest,
    *,
    extra_system_prompt: str | None = None,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": TRANSLATION_SYSTEM_PROMPT}]
    if extra_system_prompt:
        messages.append({"role": "system", "content": extra_system_prompt})
    messages.append({"role": "user", "content": build_batch_user_prompt(request)})
    return messages


def load_translation_prompt(source_path: Path, locale_dir: Path) -> str | None:
    for prompt_path in iter_translation_prompt_paths(source_path, locale_dir):
        if not prompt_path.is_file():
            continue
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        if prompt_text:
            return prompt_text
    return None


def iter_translation_prompt_paths(
    source_path: Path, locale_dir: Path
) -> tuple[Path, ...]:
    source_dir = source_path if source_path.is_dir() else source_path.parent
    candidates = (
        locale_dir / TRANSLATION_PROMPT_FILE_NAME,
        source_dir / TRANSLATION_PROMPT_FILE_NAME,
        Path.cwd() / TRANSLATION_PROMPT_FILE_NAME,
    )
    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)
        unique_candidates.append(resolved_candidate)
    return tuple(unique_candidates)


def parse_batch_response(
    content: str,
    request: BatchTranslationRequest,
) -> dict[str, TranslationResult]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model returned invalid JSON: {content}") from exc

    items = data.get("translations")
    if not isinstance(items, list):
        raise RuntimeError(f"Model response missing translations: {content}")

    expected_locales = {target.locale for target in request.targets}
    parsed_results: dict[str, TranslationResult] = {}

    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise RuntimeError(f"Model response item is not an object: {content}")

        item_locale = raw_item.get("locale")
        text = raw_item.get("text")
        needs_review = raw_item.get("needs_review", False)
        issues = raw_item.get("issues", [])

        if not isinstance(item_locale, str) or item_locale not in expected_locales:
            raise RuntimeError(f"Model response returned unknown locale: {content}")
        if not isinstance(text, str) or not text:
            raise RuntimeError(f"Model response missing translated text: {content}")
        if not isinstance(needs_review, bool):
            raise RuntimeError(
                f"Model response needs_review must be boolean: {content}"
            )
        if not isinstance(issues, list) or not all(
            isinstance(issue, str) for issue in issues
        ):
            raise RuntimeError(
                f"Model response issues must be a list of strings: {content}"
            )

        validate_translated_text(request.source_text, text)

        parsed_results[item_locale] = TranslationResult(
            locale=item_locale,
            text=text,
            needs_review=needs_review,
            issues=tuple(issues),
        )

    if set(parsed_results) != expected_locales:
        raise RuntimeError(
            "Model response locales do not match request locales. "
            f"expected={sorted(expected_locales)} got={sorted(parsed_results)}"
        )

    return parsed_results


def validate_translated_text(source_text: str, translated_text: str) -> None:
    source_specs = [
        build_placeholder_spec(expr) for expr in extract_placeholders(source_text)
    ]
    translated_exprs = extract_placeholders(translated_text)

    if len(source_specs) != len(translated_exprs):
        raise RuntimeError(
            "Translated placeholder count does not match source template: "
            f"source={source_text!r} translated={translated_text!r}"
        )

    remaining = list(source_specs)
    for translated_expr in translated_exprs:
        matched_index = find_matching_placeholder_index(remaining, translated_expr)
        if matched_index is None:
            raise RuntimeError(
                "Translated placeholder is not compatible with source template: "
                f"source={source_text!r} translated={translated_text!r}"
            )
        remaining.pop(matched_index)


def find_matching_placeholder_index(
    source_specs: list[PlaceholderSpec],
    translated_expression: str,
) -> int | None:
    for index, source_spec in enumerate(source_specs):
        if placeholder_matches(source_spec, translated_expression):
            return index
    return None


def placeholder_matches(
    source_spec: PlaceholderSpec, translated_expression: str
) -> bool:
    translated_node = parse_expression(translated_expression)
    if translated_node is None:
        return False

    translated_normalized = normalize_expression(translated_expression)
    if translated_normalized is None:
        return False

    if source_spec.requires_exact_match:
        return translated_normalized == source_spec.normalized_expression

    if translated_normalized == source_spec.normalized_expression:
        return True

    return is_allowed_wrapper_for_source(
        source_spec.normalized_expression, translated_node
    )


def build_placeholder_spec(expression: str) -> PlaceholderSpec:
    normalized = normalize_expression(expression)
    if normalized is None:
        raise RuntimeError(f"Invalid source placeholder expression: {expression}")

    return PlaceholderSpec(
        source_expression=expression,
        normalized_expression=normalized,
        requires_exact_match=is_allowed_fmt_expression(expression),
    )


def is_allowed_wrapper_for_source(source_normalized: str, node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if node.keywords:
        return False

    func_name = get_fmt_function_name(node.func)
    if func_name not in ALLOWED_FMT_FUNCS:
        return False

    if func_name in {
        "date",
        "time",
        "datetime",
        "decimal",
        "number",
        "percent",
        "timedelta",
        "compact_decimal",
    }:
        if len(node.args) != 1:
            return False
    elif func_name == "currency":
        if len(node.args) != 2 or not is_string_literal(node.args[1]):
            return False
    elif func_name == "compact_currency":
        if len(node.args) != 2 or not is_string_literal(node.args[1]):
            return False

    if func_name == "percent":
        return normalize_node(node.args[0]) == source_normalized or is_divided_by_100(
            node.args[0], source_normalized
        )

    if func_name == "compact_decimal":
        return normalize_node(
            node.args[0]
        ) == source_normalized or is_multiplied_compact(node.args[0], source_normalized)

    if func_name == "compact_currency":
        return normalize_node(
            node.args[0]
        ) == source_normalized or is_multiplied_compact(node.args[0], source_normalized)

    return normalize_node(node.args[0]) == source_normalized


def is_divided_by_100(node: ast.AST, source_normalized: str) -> bool:
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
        return False
    return normalize_node(node.left) == source_normalized and is_numeric_constant(
        node.right, 100
    )


def is_multiplied_compact(node: ast.AST, source_normalized: str) -> bool:
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
        return False

    left_normalized = normalize_node(node.left)
    right_normalized = normalize_node(node.right)
    if left_normalized == source_normalized and is_compact_scale_constant(node.right):
        return True
    if right_normalized == source_normalized and is_compact_scale_constant(node.left):
        return True
    return False


def is_compact_scale_constant(node: ast.AST) -> bool:
    return any(is_numeric_constant(node, value) for value in COMPACT_SCALE_VALUES)


def is_numeric_constant(node: ast.AST, value: int) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def is_string_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def is_allowed_fmt_expression(expression: str) -> bool:
    node = parse_expression(expression)
    if not isinstance(node, ast.Call):
        return False
    func_name = get_fmt_function_name(node.func)
    return func_name in ALLOWED_FMT_FUNCS


def get_fmt_function_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Attribute):
        return None
    if not isinstance(node.value, ast.Name) or node.value.id != "fmt":
        return None
    return node.attr


def extract_placeholders(text: str) -> list[str]:
    return [match.group(1).strip() for match in PLACEHOLDER_PATTERN.finditer(text)]


def parse_expression(expression: str) -> ast.AST | None:
    try:
        return ast.parse(expression, mode="eval").body
    except SyntaxError:
        return None


def normalize_expression(expression: str) -> str | None:
    node = parse_expression(expression)
    if node is None:
        return None
    return normalize_node(node)


def normalize_node(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def should_translate_entry(current_text: str | None, overwrite: bool) -> bool:
    if overwrite:
        return True

    return current_text == MISSING_TRANSLATION


def chunked(items: list[TranslationTask], size: int) -> list[list[TranslationTask]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
