from __future__ import annotations

import argparse
import ast
import json
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

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

TRANSLATION_SYSTEM_PROMPT = """You are a localization rewrite engine for python template strings with Babel CLDR formatting.

Task:
Rewrite each source template for the target locale while preserving placeholders.
Use the source template together with the cue from static analysis.
Source entries can contain mixed languages.
For each item, first determine whether it already reads naturally for the target locale. If it already fits the target locale, keep it unchanged.
If it does not fit the target locale, translate or adapt it for the target locale.

Output format:
Return JSON only:
{
  "items": [
    {
      "id": "0",
      "text": "...",
      "needs_review": false,
      "issues": []
    }
  ]
}

Allowed placeholder forms in output:
- {name}
- {fmt.date(name)}
- {fmt.time(name)}
- {fmt.datetime(name)}
- {fmt.decimal(name)}
- {fmt.number(name)}
- {fmt.currency(name, "USD")}
- {fmt.compact_decimal(name)}
- {fmt.compact_currency(name, "USD")}
- {fmt.percent(name)}
- {fmt.timedelta(name)}
- {fmt.compact_decimal(name * 1000)}
- {fmt.compact_decimal(name * 1000000)}
- {fmt.compact_decimal(name * 1000000000)}
- {fmt.compact_currency(name * 1000, "USD")}
- {fmt.compact_currency(name * 1000000, "USD")}
- {fmt.compact_currency(name * 1000000000, "USD")}
- {fmt.percent(name / 100)}

Hard rules:
1. Preserve the number of placeholders.
2. Never rename, invent, or delete placeholders.
3. Only change a placeholder by keeping it unchanged or wrapping the original expression with one allowed fmt helper.
4. If the source template already contains an allowed fmt helper, keep that placeholder expression exactly.
5. Do not output arbitrary code, indexing, attribute access, or method calls other than allowed fmt helpers.
6. If the cue strongly indicates date, time, datetime, currency, percent, compact number, or timedelta formatting, you may apply the matching fmt helper.
7. If the cue includes allowed candidates, stay within those candidates unless the source already uses an allowed fmt helper.
8. If the cue is weak or ambiguous, keep the placeholder unchanged.
9. If the text is already appropriate for the target locale, return it unchanged.
10. Return one item for every input id.
11. Do not explain your reasoning.
12. Return JSON only.
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
class BatchTranslationItem:
    id: str
    key: str
    source_text: str
    cue_text: str


@dataclass(frozen=True, slots=True)
class BatchTranslationRequest:
    target_locale: str
    target_language: str
    items: tuple[BatchTranslationItem, ...]


@dataclass(frozen=True, slots=True)
class TranslationResult:
    id: str
    text: str
    needs_review: bool = False
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchTranslationOutcome:
    target_locale: str
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
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def translate_batch(
        self, request: BatchTranslationRequest
    ) -> dict[str, TranslationResult]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": build_batch_user_prompt(request)},
            ],
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


def handle_translate_command(args: argparse.Namespace) -> int:
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
    batch_size = max(1, args.batch_size)

    client = OpenAICompatibleClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=args.timeout,
    )

    target_locales = [normalize_locale_name(path.stem) for path in locale_files]
    source_cues = load_shared_cues(locale_dir)
    target_entries_by_locale: dict[str, dict[str, str]] = {}
    pending_by_locale: dict[str, list[TranslationTask]] = {}

    for target_locale in target_locales:
        target_path = locale_dir / f"{target_locale}.toml"
        target_entries = load_string_table(str(target_path))
        target_entries_by_locale[target_locale] = target_entries
        pending_tasks = build_translation_tasks(
            source_entries=source_entries,
            source_cues=source_cues,
            target_locale=target_locale,
            overwrite=args.overwrite,
            current_entries=target_entries,
        )
        if pending_tasks:
            pending_by_locale[target_locale] = pending_tasks

    if not pending_by_locale:
        print(
            tt(
                f"Updated {len(target_locales)} locale file(s), translated 0 entry/entries."
            )
        )
        return 0

    outcomes = run_translation_batches(
        client=client,
        pending_by_locale=pending_by_locale,
        workers=workers,
        batch_size=batch_size,
    )

    total_translated = 0
    for outcome in outcomes:
        target_entries = target_entries_by_locale[outcome.target_locale]
        tasks_by_id = {
            task.key: task for task in pending_by_locale[outcome.target_locale]
        }
        for result in outcome.results:
            task = tasks_by_id[result.id]
            target_entries[task.key] = result.text
            total_translated += 1

    if not args.dry_run:
        for target_locale, target_entries in target_entries_by_locale.items():
            write_string_table(
                str(locale_dir / f"{target_locale}.toml"), target_entries
            )

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
    target_locale: str,
    overwrite: bool,
    current_entries: dict[str, str],
) -> list[TranslationTask]:
    target_language = locale_display_name(target_locale)
    tasks: list[TranslationTask] = []

    for key in source_entries:
        current_text = current_entries.get(key)
        if not should_translate_entry(current_text, overwrite):
            continue

        tasks.append(
            TranslationTask(
                key=key,
                source_text=key,
                cue_text=source_cues.get(key, ""),
                target_locale=target_locale,
                target_language=target_language,
            )
        )

    return tasks


def run_translation_batches(
    *,
    client: OpenAICompatibleClient,
    pending_by_locale: dict[str, list[TranslationTask]],
    workers: int,
    batch_size: int,
) -> list[BatchTranslationOutcome]:
    batch_requests: list[BatchTranslationRequest] = []
    for target_locale, tasks in pending_by_locale.items():
        for chunk in chunked(tasks, batch_size):
            items = tuple(
                BatchTranslationItem(
                    id=task.key,
                    key=task.key,
                    source_text=task.source_text,
                    cue_text=task.cue_text,
                )
                for task in chunk
            )
            batch_requests.append(
                BatchTranslationRequest(
                    target_locale=target_locale,
                    target_language=chunk[0].target_language,
                    items=items,
                )
            )

    outcomes: list[BatchTranslationOutcome] = []
    if workers == 1 or len(batch_requests) == 1:
        for batch_request in batch_requests:
            results = validate_batch_results(
                batch_request, client.translate_batch(batch_request)
            )
            outcomes.append(
                BatchTranslationOutcome(
                    target_locale=batch_request.target_locale,
                    results=tuple(results[item.id] for item in batch_request.items),
                )
            )
        return outcomes

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(client.translate_batch, batch_request): batch_request
            for batch_request in batch_requests
        }
        for future in as_completed(future_map):
            batch_request = future_map[future]
            results = validate_batch_results(batch_request, future.result())
            outcomes.append(
                BatchTranslationOutcome(
                    target_locale=batch_request.target_locale,
                    results=tuple(results[item.id] for item in batch_request.items),
                )
            )

    return outcomes


def validate_batch_results(
    request: BatchTranslationRequest,
    results: dict[str, TranslationResult],
) -> dict[str, TranslationResult]:
    expected_ids = {item.id for item in request.items}
    if set(results) != expected_ids:
        raise RuntimeError(
            f"Batch result ids do not match request ids. expected={sorted(expected_ids)} got={sorted(results)}"
        )

    source_by_id = {item.id: item for item in request.items}
    for item_id, result in results.items():
        validate_translated_text(source_by_id[item_id].source_text, result.text)

    return results


def build_batch_user_prompt(request: BatchTranslationRequest) -> str:
    lines = [
        f"Target language: {request.target_language}",
        f"Target locale: {request.target_locale}",
        "Important: source entries come from TOML keys and may be mixed-language. Decide per item whether translation is needed.",
        "",
        "Translate every item below and return one JSON output item for every id.",
        "",
    ]

    for item in request.items:
        lines.extend(
            [
                f"Item id: {item.id}",
                "Source template:",
                item.source_text,
                "",
                "Cue:",
                item.cue_text or "No additional cue.",
                "",
            ]
        )

    return "\n".join(lines)


def parse_batch_response(
    content: str,
    request: BatchTranslationRequest,
) -> dict[str, TranslationResult]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model returned invalid JSON: {content}") from exc

    items = data.get("items")
    if not isinstance(items, list):
        raise RuntimeError(f"Model response missing items: {content}")

    expected_ids = {item.id for item in request.items}
    parsed_results: dict[str, TranslationResult] = {}
    source_by_id = {item.id: item for item in request.items}

    for raw_item in items:
        if not isinstance(raw_item, dict):
            raise RuntimeError(f"Model response item is not an object: {content}")

        item_id = raw_item.get("id")
        text = raw_item.get("text")
        needs_review = raw_item.get("needs_review", False)
        issues = raw_item.get("issues", [])

        if not isinstance(item_id, str) or item_id not in expected_ids:
            raise RuntimeError(f"Model response returned unknown id: {content}")
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

        validate_translated_text(source_by_id[item_id].source_text, text)

        parsed_results[item_id] = TranslationResult(
            id=item_id,
            text=text,
            needs_review=needs_review,
            issues=tuple(issues),
        )

    if set(parsed_results) != expected_ids:
        raise RuntimeError(
            f"Model response ids do not match request ids. expected={sorted(expected_ids)} got={sorted(parsed_results)}"
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
