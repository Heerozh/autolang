from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..source_templates import extract_template_from_call, render_formatted_value
from .pyright_lsp import infer_type


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    line: int
    source: str
    annotation: str | None = None


@dataclass(frozen=True, slots=True)
class PlaceholderCue:
    placeholder: str
    expression: str
    definition: DefinitionRecord | None
    annotation: str | None
    allowed_candidates: tuple[str, ...]
    recommended: str
    confidence: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StaticTemplateCue:
    template: str
    line: int
    cue_text: str


@dataclass(slots=True)
class _Scope:
    parent: "_Scope | None" = None
    definitions: dict[str, DefinitionRecord] = field(default_factory=dict)

    def add_definition(self, name: str, record: DefinitionRecord) -> None:
        self.definitions[name] = record

    def lookup(self, name: str) -> DefinitionRecord | None:
        record = self.definitions.get(name)
        if record is not None:
            return record
        if self.parent is not None:
            return self.parent.lookup(name)
        return None


class StaticCueAnalyzer(ast.NodeVisitor):
    def __init__(
        self,
        source: str,
        *,
        filename: str | None = None,
        parent_map: dict[ast.AST, ast.AST] | None = None,
    ):
        self.filename = filename or None
        self.templates: list[StaticTemplateCue] = []
        self._scope = _Scope()
        self._source = source
        self._source_lines = source.splitlines(keepends=True)
        self._parent_map = parent_map or {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        with self._child_scope():
            self._record_parameters(node.args)
            self._visit_statements(node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        with self._child_scope():
            self._record_parameters(node.args)
            self._visit_statements(node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        with self._child_scope():
            self._visit_statements(node.body)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        value_source = ast.unparse(node.value)
        for target in node.targets:
            self._record_binding(
                target,
                line=node.lineno,
                source=f"{ast.unparse(target)} = {value_source}",
            )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            value_source = ast.unparse(node.value)
        else:
            value_source = None

        annotation = ast.unparse(node.annotation)
        target_source = ast.unparse(node.target)
        source = f"{target_source}: {annotation}"
        if value_source is not None:
            source = f"{source} = {value_source}"
        self._record_binding(
            node.target,
            line=node.lineno,
            source=source,
            annotation=annotation,
        )

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        symbol = _AUGASSIGN_SYMBOLS.get(type(node.op), "")
        self._record_binding(
            node.target,
            line=node.lineno,
            source=f"{ast.unparse(node.target)} {symbol}= {ast.unparse(node.value)}",
        )

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        is_async = isinstance(node, ast.AsyncFor)
        prefix = "async for" if is_async else "for"
        self._record_binding(
            node.target,
            line=node.lineno,
            source=f"{prefix} {ast.unparse(node.target)} in {ast.unparse(node.iter)}",
        )
        self._visit_statements(node.body)
        self._visit_statements(node.orelse)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        is_async = isinstance(node, ast.AsyncWith)
        prefix = "async with" if is_async else "with"
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._record_binding(
                    item.optional_vars,
                    line=node.lineno,
                    source=(
                        f"{prefix} {ast.unparse(item.context_expr)} "
                        f"as {ast.unparse(item.optional_vars)}"
                    ),
                )
        self._visit_statements(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        with self._child_scope():
            if node.name:
                exception_type = (
                    ast.unparse(node.type) if node.type is not None else "Exception"
                )
                self._record_name(
                    node.name,
                    line=node.lineno,
                    source=f"except {exception_type} as {node.name}",
                )
            self._visit_statements(node.body)

    def visit_Call(self, node: ast.Call) -> None:
        template, _variables = extract_template_from_call(node)
        if (
            template is not None
            and isinstance(node.func, ast.Name)
            and node.func.id == "tt"
        ):
            self.templates.append(
                StaticTemplateCue(
                    template=template,
                    line=node.lineno,
                    cue_text=self._build_template_cue(node, template),
                )
            )
        self.generic_visit(node)

    def _record_parameters(self, args: ast.arguments) -> None:
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            annotation = (
                ast.unparse(arg.annotation) if arg.annotation is not None else None
            )
            self._record_name(
                arg.arg,
                line=arg.lineno,
                source=_format_parameter_source(arg.arg, annotation),
                annotation=annotation,
            )
        if args.vararg is not None:
            annotation = (
                ast.unparse(args.vararg.annotation)
                if args.vararg.annotation is not None
                else None
            )
            self._record_name(
                args.vararg.arg,
                line=args.vararg.lineno,
                source=_format_parameter_source(f"*{args.vararg.arg}", annotation),
                annotation=annotation,
            )
        if args.kwarg is not None:
            annotation = (
                ast.unparse(args.kwarg.annotation)
                if args.kwarg.annotation is not None
                else None
            )
            self._record_name(
                args.kwarg.arg,
                line=args.kwarg.lineno,
                source=_format_parameter_source(f"**{args.kwarg.arg}", annotation),
                annotation=annotation,
            )

    def _visit_statements(self, body: list[ast.stmt]) -> None:
        for statement in body:
            self.visit(statement)

    @contextmanager
    def _child_scope(self):
        previous_scope = self._scope
        self._scope = _Scope(parent=self._scope)
        try:
            yield
        finally:
            self._scope = previous_scope

    def _record_binding(
        self,
        target: ast.AST,
        *,
        line: int,
        source: str,
        annotation: str | None = None,
    ) -> None:
        for name in _extract_target_names(target):
            self._record_name(name, line=line, source=source, annotation=annotation)

    def _record_name(
        self,
        name: str,
        *,
        line: int,
        source: str,
        annotation: str | None = None,
    ) -> None:
        self._scope.add_definition(
            name,
            DefinitionRecord(line=line, source=source, annotation=annotation),
        )

    def _build_template_cue(self, node: ast.Call, template: str) -> str:
        location = (
            f"{self.filename}:{node.lineno}" if self.filename else f"line {node.lineno}"
        )
        del template  # Unused for current
        lines = [f"Location: {location}"]

        arg = node.args[0] if node.args else None
        if not isinstance(arg, ast.JoinedStr):
            lines.append("No placeholders.")
            return "\n".join(lines)

        placeholder_cues = [
            self._build_placeholder_cue(value)
            for value in arg.values
            if isinstance(value, ast.FormattedValue)
        ]
        if not placeholder_cues:
            lines.append("No placeholders.")
            return "\n".join(lines)

        for cue in placeholder_cues:
            lines.extend(
                [
                    "",
                    f"Placeholder: {cue.placeholder}",
                    f"Expression: {cue.expression}",
                    f"Definition: {
                        cue.definition.source
                        if cue.definition is not None
                        else 'not found in local static scope'
                    }",
                    f"Annotation: {cue.annotation or 'unknown'}",
                    f"Allowed candidates: {', '.join(cue.allowed_candidates)}",
                    f"Recommended: {cue.recommended}",
                    f"Confidence: {cue.confidence}",
                ]
            )
            if cue.notes:
                lines.append(f"Notes: {'; '.join(cue.notes)}")

        return "\n".join(lines)

    def _build_placeholder_cue(self, node: ast.FormattedValue) -> PlaceholderCue:
        placeholder, _nested = render_formatted_value(node)
        expression = ast.unparse(node.value)
        definition = (
            self._scope.lookup(node.value.id)
            if isinstance(node.value, ast.Name)
            else None
        )
        annotation = self._infer_annotation(node.value)
        allowed_candidates, recommended, confidence, notes = (
            suggest_placeholder_candidates(
                expression=expression,
                placeholder=placeholder,
                annotation=annotation,
                definition_source=definition.source if definition is not None else None,
                has_conversion=node.conversion >= 0,
                has_format_spec=isinstance(node.format_spec, ast.JoinedStr),
            )
        )
        return PlaceholderCue(
            placeholder=placeholder,
            expression=expression,
            definition=definition,
            annotation=annotation,
            allowed_candidates=allowed_candidates,
            recommended=recommended,
            confidence=confidence,
            notes=notes,
        )

    def _infer_annotation(self, node: ast.expr) -> str | None:
        pyright_annotation = self._infer_annotation_from_pyright(node)
        if pyright_annotation is not None:
            return pyright_annotation

        if isinstance(node, ast.Name):
            definition = self._scope.lookup(node.id)
            if definition is not None:
                return definition.annotation
        return None

    def _infer_annotation_from_pyright(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return infer_type(
                source=self._source,
                filename=self.filename,
                line=node.lineno,
                col=node.col_offset,
            )

        expression = ast.unparse(node)
        probe_line_number = self._probe_line_number(node)
        indent = self._detect_indent(probe_line_number)
        probe_line = f"{indent}__autolang_probe__ = {expression}\n"
        modified_lines = list(self._source_lines)
        modified_lines.insert(probe_line_number - 1, probe_line)
        modified_source = "".join(modified_lines)
        return infer_type(
            source=modified_source,
            filename=self._probe_filename(probe_line_number),
            line=probe_line_number,
            col=len(indent),
        )

    def _probe_line_number(self, node: ast.AST) -> int:
        statement = self._enclosing_statement(node)
        return statement.lineno

    def _enclosing_statement(self, node: ast.AST) -> ast.stmt:
        current = node
        while not isinstance(current, ast.stmt):
            parent = self._parent_map.get(current)
            if parent is None:
                raise ValueError("Unable to locate enclosing statement")
            current = parent
        return current

    def _detect_indent(self, line: int) -> str:
        if line <= 0 or line > len(self._source_lines):
            return ""
        text = self._source_lines[line - 1]
        return text[: len(text) - len(text.lstrip())]

    def _probe_filename(self, line: int) -> str:
        base = self.filename or "autolang_inline.py"
        return f"{base}.autolang-probe-{line}.py"


def analyze_static_cues(
    source: str, *, filename: str | None = None
) -> list[StaticTemplateCue]:
    module = ast.parse(source)
    parent_map = {
        child: parent
        for parent in ast.walk(module)
        for child in ast.iter_child_nodes(parent)
    }
    analyzer = StaticCueAnalyzer(source, filename=filename, parent_map=parent_map)
    analyzer.visit(module)
    return analyzer.templates


def suggest_placeholder_candidates(
    *,
    expression: str,
    placeholder: str,
    annotation: str | None,
    definition_source: str | None,
    has_conversion: bool,
    has_format_spec: bool,
) -> tuple[tuple[str, ...], str, str, tuple[str, ...]]:
    base_candidate = placeholder
    notes: list[str] = []

    if has_conversion:
        return (
            (base_candidate,),
            base_candidate,
            "high",
            ("Source placeholder already uses an f-string conversion.",),
        )
    if has_format_spec:
        return (
            (base_candidate,),
            base_candidate,
            "high",
            ("Source placeholder already uses an f-string format spec.",),
        )
    if _is_fmt_call(expression):
        return (
            (base_candidate,),
            base_candidate,
            "high",
            ("Source placeholder already calls fmt.*.",),
        )

    kind = _infer_placeholder_kind(
        annotation=annotation, definition_source=definition_source
    )
    candidates = _build_greedy_candidates(expression, placeholder, kind=kind)
    recommended = _recommended_candidate(expression, placeholder, kind=kind)
    confidence = "high" if recommended != base_candidate else "low"

    if kind == "unknown":
        notes.append(
            "Candidates are intentionally greedy; only candidates ruled out by exact "
            "static information were removed."
        )
    elif kind == "text":
        notes.append(
            "Static information identifies this placeholder as text-like, "
            "so fmt.* wrappers were pruned."
        )
    elif kind == "boolean":
        notes.append(
            "Static information identifies this placeholder as boolean-like, "
            "so fmt.* wrappers were pruned."
        )
    elif kind == "none":
        notes.append(
            "Static information identifies this placeholder as None-like, "
            "so fmt.* wrappers were pruned."
        )
    elif kind == "number":
        notes.append(
            "Static information identifies this placeholder as numeric, "
            "so date/time wrappers were pruned."
        )
    elif kind == "date":
        notes.append(
            "Static information identifies this placeholder as date-like, "
            "so numeric and timedelta wrappers were pruned."
        )
    elif kind == "time":
        notes.append(
            "Static information identifies this placeholder as time-like, "
            "so non-time wrappers were pruned."
        )
    elif kind == "datetime":
        notes.append("Static information identifies this placeholder as datetime-like.")
    elif kind == "timedelta":
        notes.append(
            "Static information identifies this placeholder as timedelta-like, "
            "so unrelated wrappers were pruned."
        )

    return candidates, recommended, confidence, tuple(notes)


def _extract_target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _extract_target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_extract_target_names(element))
        return names
    return []


def _is_fmt_call(expression: str) -> bool:
    try:
        node = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return False
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "fmt"
    )


def _infer_placeholder_kind(
    annotation: str | None, definition_source: str | None
) -> str:
    annotation_kind = _infer_kind_from_annotation(annotation)
    definition_kind = _infer_kind_from_definition(definition_source)

    if (
        annotation_kind is not None
        and definition_kind is not None
        and annotation_kind != definition_kind
    ):
        return "unknown"
    if annotation_kind is not None:
        return annotation_kind
    if definition_kind is not None:
        return definition_kind
    return "unknown"


def _infer_kind_from_annotation(annotation: str | None) -> str | None:
    if not annotation:
        return None

    normalized = annotation.replace(" ", "").lower()
    union_parts = (
        normalized.replace("optional[", "")
        .replace("]", "")
        .replace("none", "nonetype")
        .split("|")
    )
    recognized = {
        part_kind
        for part in union_parts
        if (part_kind := _kind_from_type_name(part)) is not None
    }
    recognized.discard("none")
    if len(recognized) == 1:
        return next(iter(recognized))
    if len(recognized) > 1:
        return None
    if _annotation_defaults_to_text(normalized):
        return "text"
    return None


def _infer_kind_from_definition(definition_source: str | None) -> str | None:
    if not definition_source or "=" not in definition_source:
        return None

    value_source = definition_source.split("=", 1)[1].strip()
    try:
        node = ast.parse(value_source, mode="eval").body
    except SyntaxError:
        return None

    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return "text"
        if isinstance(node.value, bool):
            return "boolean"
        if node.value is None:
            return "none"
        if isinstance(node.value, (int, float, complex)):
            return "number"

    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
    ):
        if isinstance(node.operand.value, (int, float, complex)):
            return "number"

    if isinstance(node, ast.Call):
        func_name = ast.unparse(node.func).lower()
        return _kind_from_type_name(func_name)

    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return "text"

    return None


def _kind_from_type_name(type_name: str) -> str | None:
    normalized = type_name.replace(" ", "").lower()
    type_head = _type_head(normalized)
    terminal = type_head.rsplit(".", 1)[-1]

    if terminal in {
        "str",
        "literalstring",
        "path",
        "purepath",
        "pathlike",
        "list",
        "dict",
        "set",
        "tuple",
        "sequence",
        "mapping",
        "iterable",
    }:
        return "text"
    if terminal == "bool":
        return "boolean"
    if terminal in {"nonetype", "none"}:
        return "none"
    if terminal in {"int", "float", "decimal", "fraction"}:
        return "number"
    if type_head.endswith("datetime.datetime") or terminal == "datetime":
        return "datetime"
    if type_head.endswith("datetime.date") or terminal == "date":
        return "date"
    if type_head.endswith("datetime.time") or terminal == "time":
        return "time"
    if type_head.endswith("datetime.timedelta") or terminal == "timedelta":
        return "timedelta"
    return None


def _annotation_defaults_to_text(annotation: str) -> bool:
    if not annotation or annotation in {"any", "unknown", "typing.any"}:
        return False
    return True


def _type_head(type_name: str) -> str:
    return type_name.split("[", 1)[0]


def _build_greedy_candidates(
    expression: str, placeholder: str, *, kind: str
) -> tuple[str, ...]:
    base = [placeholder]
    datetime_candidates = [
        f"{{fmt.date({expression})}}",
        f"{{fmt.time({expression})}}",
        f"{{fmt.datetime({expression})}}",
    ]
    numeric_candidates = [
        f"{{fmt.decimal({expression})}}",
        f"{{fmt.number({expression})}}",
        f'{{fmt.currency({expression}, "USD")}}',
        f"{{fmt.compact_decimal({expression})}}",
        f'{{fmt.compact_currency({expression}, "USD")}}',
        f"{{fmt.compact_decimal({expression} * 1000)}}",
        f"{{fmt.compact_decimal({expression} * 1000000)}}",
        f"{{fmt.compact_decimal({expression} * 1000000000)}}",
        f'{{fmt.compact_currency({expression} * 1000, "USD")}}',
        f'{{fmt.compact_currency({expression} * 1000000, "USD")}}',
        f'{{fmt.compact_currency({expression} * 1000000000, "USD")}}',
        f"{{fmt.percent({expression})}}",
        f"{{fmt.percent({expression} / 100)}}",
    ]
    timedelta_candidates = [f"{{fmt.timedelta({expression})}}"]

    if kind in {"text", "boolean", "none"}:
        return tuple(base)
    if kind == "number":
        return tuple(base + numeric_candidates + timedelta_candidates)
    if kind == "date":
        return tuple(base + [datetime_candidates[0], datetime_candidates[2]])
    if kind == "time":
        return tuple(base + [datetime_candidates[1]])
    if kind == "datetime":
        return tuple(base + datetime_candidates)
    if kind == "timedelta":
        return tuple(base + timedelta_candidates)

    return tuple(base + datetime_candidates + numeric_candidates + timedelta_candidates)


def _recommended_candidate(expression: str, placeholder: str, *, kind: str) -> str:
    if kind == "date":
        return f"{{fmt.date({expression})}}"
    if kind == "time":
        return f"{{fmt.time({expression})}}"
    if kind == "datetime":
        return f"{{fmt.datetime({expression})}}"
    if kind == "timedelta":
        return f"{{fmt.timedelta({expression})}}"
    return placeholder


def _format_parameter_source(name: str, annotation: str | None) -> str:
    if annotation:
        return f"parameter {name}: {annotation}"
    return f"parameter {name}"


_AUGASSIGN_SYMBOLS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Mod: "%",
}
