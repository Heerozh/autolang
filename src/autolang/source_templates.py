from __future__ import annotations

import ast


def extract_template_from_call(
    node: ast.AST | None,
) -> tuple[str | None, tuple[str, ...]]:
    if not isinstance(node, ast.Call) or not node.args:
        return None, ()

    arg = node.args[0]
    if isinstance(arg, ast.Constant):
        return str(arg.value), ()

    if not isinstance(arg, ast.JoinedStr):
        return None, ()

    parts: list[str] = []
    variables: list[str] = []

    for value in arg.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
            continue

        if isinstance(value, ast.FormattedValue):
            rendered, expressions = render_formatted_value(value)
            parts.append(rendered)
            variables.extend(expressions)

    return "".join(parts), tuple(variables)


def render_joined_str(node: ast.JoinedStr) -> tuple[str, tuple[str, ...]]:
    parts: list[str] = []
    expressions: list[str] = []

    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
            continue

        if isinstance(value, ast.FormattedValue):
            rendered, nested_expressions = render_formatted_value(value)
            parts.append(rendered)
            expressions.extend(nested_expressions)

    return "".join(parts), tuple(expressions)


def render_formatted_value(node: ast.FormattedValue) -> tuple[str, tuple[str, ...]]:
    expression = ast.unparse(node.value)
    conversion = "" if node.conversion < 0 else f"!{chr(node.conversion)}"
    format_spec = ""
    nested_expressions: tuple[str, ...] = ()

    if isinstance(node.format_spec, ast.JoinedStr):
        rendered_spec, nested_expressions = render_joined_str(node.format_spec)
        format_spec = f":{rendered_spec}"

    return f"{{{expression}{conversion}{format_spec}}}", (
        expression,
        *nested_expressions,
    )
