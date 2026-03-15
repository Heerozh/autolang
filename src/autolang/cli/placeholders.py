from __future__ import annotations

import ast
import re
from dataclasses import dataclass

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
class PlaceholderSpec:
    source_expression: str
    normalized_expression: str
    requires_exact_match: bool


def validate_translated_text(
    source_text: str,
    translated_text: str,
    *,
    cue_text: str | None = None,
) -> None:
    source_specs = [
        build_placeholder_spec(expr) for expr in extract_placeholders(source_text)
    ]
    translated_exprs = extract_placeholders(translated_text)
    allowed_candidates = extract_allowed_candidate_sets(
        cue_text=cue_text, count=len(source_specs)
    )

    if len(source_specs) != len(translated_exprs):
        raise RuntimeError(
            "Translated placeholder count does not match source template: "
            f"source={source_text!r} translated={translated_text!r}"
        )

    remaining = list(source_specs)
    remaining_allowed_candidates = (
        list(allowed_candidates) if allowed_candidates is not None else None
    )
    for translated_expr in translated_exprs:
        matched_index = find_matching_placeholder_index(
            remaining,
            translated_expr,
            allowed_candidate_sets=remaining_allowed_candidates,
        )
        if matched_index is None:
            raise RuntimeError(
                "Translated placeholder is not compatible with source template: "
                f"source={source_text!r} translated={translated_text!r}"
            )
        remaining.pop(matched_index)
        if remaining_allowed_candidates is not None:
            remaining_allowed_candidates.pop(matched_index)


def find_matching_placeholder_index(
    source_specs: list[PlaceholderSpec],
    translated_expression: str,
    *,
    allowed_candidate_sets: list[set[str]] | None = None,
) -> int | None:
    for index, source_spec in enumerate(source_specs):
        allowed_candidates = (
            allowed_candidate_sets[index]
            if allowed_candidate_sets is not None
            else None
        )
        if placeholder_matches(
            source_spec,
            translated_expression,
            allowed_candidates=allowed_candidates,
        ):
            return index
    return None


def placeholder_matches(
    source_spec: PlaceholderSpec,
    translated_expression: str,
    *,
    allowed_candidates: set[str] | None = None,
) -> bool:
    translated_node = parse_expression(translated_expression)
    if translated_node is None:
        return False

    translated_normalized = normalize_expression(translated_expression)
    if translated_normalized is None:
        return False

    if (
        allowed_candidates is not None
        and translated_normalized not in allowed_candidates
    ):
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


def extract_allowed_candidate_sets(
    *,
    cue_text: str | None,
    count: int,
) -> list[set[str]] | None:
    if not cue_text:
        return None

    candidate_sets: list[set[str]] = []
    for line in cue_text.splitlines():
        if not line.startswith("Allowed candidates:"):
            continue
        expressions = extract_placeholders(line.partition(":")[2].strip())
        normalized_candidates = {
            normalized
            for expression in expressions
            if (normalized := normalize_expression(expression)) is not None
        }
        candidate_sets.append(normalized_candidates)

    if len(candidate_sets) != count:
        return None

    return candidate_sets


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
