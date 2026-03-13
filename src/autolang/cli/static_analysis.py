from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field

from ..source_templates import extract_template_from_call, render_formatted_value


@dataclass(frozen=True, slots=True)
class DefinitionRecord:
    kind: str
    line: int
    source: str
    annotation: str | None = None


@dataclass(frozen=True, slots=True)
class PlaceholderCue:
    placeholder: str
    expression: str
    definition: DefinitionRecord | None
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
    definitions: dict[str, list[DefinitionRecord]] = field(default_factory=lambda: defaultdict(list))

    def add_definition(self, name: str, record: DefinitionRecord) -> None:
        self.definitions[name].append(record)

    def lookup(self, name: str) -> DefinitionRecord | None:
        records = self.definitions.get(name)
        if records:
            return records[-1]
        if self.parent is not None:
            return self.parent.lookup(name)
        return None


class StaticCueAnalyzer(ast.NodeVisitor):
    def __init__(self, *, filename: str | None = None):
        self.filename = filename
        self.templates: list[StaticTemplateCue] = []
        self._scope = _Scope()

    def visit_Module(self, node: ast.Module) -> None:
        self._visit_block(node.body)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.add_definition(
            node.name,
            DefinitionRecord(kind="function", line=node.lineno, source=f"def {node.name}(...):"),
        )
        self._visit_function(node.args, node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope.add_definition(
            node.name,
            DefinitionRecord(kind="async_function", line=node.lineno, source=f"async def {node.name}(...):"),
        )
        self._visit_function(node.args, node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.add_definition(
            node.name,
            DefinitionRecord(kind="class", line=node.lineno, source=f"class {node.name}:"),
        )
        self._with_child_scope(node.body)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        value_source = ast.unparse(node.value)
        for target in node.targets:
            self._record_targets(target, node.lineno, value_source)

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
        self._record_targets(
            node.target,
            node.lineno,
            value_source,
            annotation=annotation,
            override_source=source,
            kind="annotated_assignment",
        )

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        symbol = _AUGASSIGN_SYMBOLS.get(type(node.op), "")
        source = f"{ast.unparse(node.target)} {symbol}= {ast.unparse(node.value)}"
        self._record_targets(
            node.target,
            node.lineno,
            ast.unparse(node.value),
            override_source=source,
            kind="augmented_assignment",
        )

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self._record_targets(
            node.target,
            node.lineno,
            ast.unparse(node.iter),
            override_source=f"for {ast.unparse(node.target)} in {ast.unparse(node.iter)}",
            kind="loop_target",
        )
        self._visit_block(node.body)
        self._with_child_scope(node.orelse)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._record_targets(
                    item.optional_vars,
                    node.lineno,
                    ast.unparse(item.context_expr),
                    override_source=f"with {ast.unparse(item.context_expr)} as {ast.unparse(item.optional_vars)}",
                    kind="with_alias",
                )
        self._visit_block(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        child_scope = _Scope(parent=self._scope)
        previous_scope = self._scope
        self._scope = child_scope
        if node.name:
            exception_type = ast.unparse(node.type) if node.type is not None else "Exception"
            self._scope.add_definition(
                node.name,
                DefinitionRecord(
                    kind="exception_alias",
                    line=node.lineno,
                    source=f"except {exception_type} as {node.name}",
                ),
            )
        self._visit_block(node.body)
        self._scope = previous_scope

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self._with_child_scope(node.body)
        self._with_child_scope(node.orelse)

    def visit_Try(self, node: ast.Try) -> None:
        self._with_child_scope(node.body)
        for handler in node.handlers:
            self.visit(handler)
        self._with_child_scope(node.orelse)
        self._with_child_scope(node.finalbody)

    def visit_Call(self, node: ast.Call) -> None:
        template, _variables = extract_template_from_call(node)
        if template is not None and isinstance(node.func, ast.Name) and node.func.id == "tt":
            self.templates.append(
                StaticTemplateCue(
                    template=template,
                    line=node.lineno,
                    cue_text=self._build_template_cue(node, template),
                )
            )
        self.generic_visit(node)

    def _visit_function(self, args: ast.arguments, body: list[ast.stmt]) -> None:
        child_scope = _Scope(parent=self._scope)
        previous_scope = self._scope
        self._scope = child_scope
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            annotation = ast.unparse(arg.annotation) if arg.annotation is not None else None
            self._scope.add_definition(
                arg.arg,
                DefinitionRecord(
                    kind="parameter",
                    line=arg.lineno,
                    source=_format_parameter_source(arg.arg, annotation),
                    annotation=annotation,
                ),
            )
        if args.vararg is not None:
            annotation = ast.unparse(args.vararg.annotation) if args.vararg.annotation is not None else None
            self._scope.add_definition(
                args.vararg.arg,
                DefinitionRecord(
                    kind="vararg",
                    line=args.vararg.lineno,
                    source=_format_parameter_source(f"*{args.vararg.arg}", annotation),
                    annotation=annotation,
                ),
            )
        if args.kwarg is not None:
            annotation = ast.unparse(args.kwarg.annotation) if args.kwarg.annotation is not None else None
            self._scope.add_definition(
                args.kwarg.arg,
                DefinitionRecord(
                    kind="kwarg",
                    line=args.kwarg.lineno,
                    source=_format_parameter_source(f"**{args.kwarg.arg}", annotation),
                    annotation=annotation,
                ),
            )
        self._visit_block(body)
        self._scope = previous_scope

    def _with_child_scope(self, body: list[ast.stmt]) -> None:
        child_scope = _Scope(parent=self._scope)
        previous_scope = self._scope
        self._scope = child_scope
        self._visit_block(body)
        self._scope = previous_scope

    def _visit_block(self, body: list[ast.stmt]) -> None:
        for statement in body:
            self.visit(statement)

    def _record_targets(
        self,
        target: ast.AST,
        line: int,
        value_source: str | None,
        *,
        annotation: str | None = None,
        override_source: str | None = None,
        kind: str = "assignment",
    ) -> None:
        source = override_source
        if source is None:
            target_source = ast.unparse(target)
            source = f"{target_source} = {value_source}" if value_source is not None else target_source

        for name in _extract_target_names(target):
            self._scope.add_definition(
                name,
                DefinitionRecord(kind=kind, line=line, source=source, annotation=annotation),
            )

    def _build_template_cue(self, node: ast.Call, template: str) -> str:
        location = f"{self.filename}:{node.lineno}" if self.filename else f"line {node.lineno}"
        lines = [f"Template: {template}", f"Location: {location}"]

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
                    f"Definition: {cue.definition.source if cue.definition is not None else 'not found in local static scope'}",
                    f"Annotation: {cue.definition.annotation if cue.definition and cue.definition.annotation else 'unknown'}",
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
        definition = self._scope.lookup(node.value.id) if isinstance(node.value, ast.Name) else None
        allowed_candidates, recommended, confidence, notes = suggest_placeholder_candidates(
            expression=expression,
            placeholder=placeholder,
            annotation=definition.annotation if definition is not None else None,
            definition_source=definition.source if definition is not None else None,
            has_conversion=node.conversion >= 0,
            has_format_spec=isinstance(node.format_spec, ast.JoinedStr),
        )
        return PlaceholderCue(
            placeholder=placeholder,
            expression=expression,
            definition=definition,
            allowed_candidates=allowed_candidates,
            recommended=recommended,
            confidence=confidence,
            notes=notes,
        )


def analyze_static_cues(source: str, *, filename: str | None = None) -> list[StaticTemplateCue]:
    module = ast.parse(source)
    analyzer = StaticCueAnalyzer(filename=filename)
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
        return (base_candidate,), base_candidate, "high", ("Source placeholder already uses an f-string conversion.",)
    if has_format_spec:
        return (base_candidate,), base_candidate, "high", ("Source placeholder already uses an f-string format spec.",)
    if _is_fmt_call(expression):
        return (base_candidate,), base_candidate, "high", ("Source placeholder already calls fmt.*.",)

    kind = _infer_placeholder_kind(annotation=annotation, definition_source=definition_source)
    candidates = _build_greedy_candidates(expression, placeholder, kind=kind)
    recommended = _recommended_candidate(expression, placeholder, kind=kind)
    confidence = "high" if recommended != base_candidate else "low"

    if kind == "unknown":
        notes.append("Candidates are intentionally greedy; only candidates ruled out by exact static information were removed.")
    elif kind == "text":
        notes.append("Static information identifies this placeholder as text-like, so fmt.* wrappers were pruned.")
    elif kind == "boolean":
        notes.append("Static information identifies this placeholder as boolean-like, so fmt.* wrappers were pruned.")
    elif kind == "none":
        notes.append("Static information identifies this placeholder as None-like, so fmt.* wrappers were pruned.")
    elif kind == "number":
        notes.append("Static information identifies this placeholder as numeric, so date/time wrappers were pruned.")
    elif kind == "date":
        notes.append("Static information identifies this placeholder as date-like, so numeric and timedelta wrappers were pruned.")
    elif kind == "time":
        notes.append("Static information identifies this placeholder as time-like, so non-time wrappers were pruned.")
    elif kind == "datetime":
        notes.append("Static information identifies this placeholder as datetime-like.")
    elif kind == "timedelta":
        notes.append("Static information identifies this placeholder as timedelta-like, so unrelated wrappers were pruned.")

    return candidates, recommended, confidence, tuple(notes)


def _extract_target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
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


def _infer_placeholder_kind(annotation: str | None, definition_source: str | None) -> str:
    annotation_kind = _infer_kind_from_annotation(annotation)
    definition_kind = _infer_kind_from_definition(definition_source)

    if annotation_kind is not None and definition_kind is not None and annotation_kind != definition_kind:
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

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)) and isinstance(node.operand, ast.Constant):
        if isinstance(node.operand.value, (int, float, complex)):
            return "number"

    if isinstance(node, ast.Call):
        func_name = ast.unparse(node.func).lower()
        return _kind_from_type_name(func_name)

    return None


def _kind_from_type_name(type_name: str) -> str | None:
    normalized = type_name.lower()
    if normalized.endswith(("str", "builtins.str", "literalstring")):
        return "text"
    if normalized.endswith(("bool", "builtins.bool")):
        return "boolean"
    if normalized.endswith(("nonetype", "none")):
        return "none"
    if normalized.endswith(("int", "float", "decimal", "decimal.decimal", "fraction", "fractions.fraction")):
        return "number"
    if normalized.endswith(("datetime.datetime", "datetime")):
        return "datetime"
    if normalized.endswith(("datetime.date", "date")) and not normalized.endswith(("datetime.datetime",)):
        return "date"
    if normalized.endswith(("datetime.time", "time")):
        return "time"
    if normalized.endswith(("datetime.timedelta", "timedelta")):
        return "timedelta"
    return None


def _build_greedy_candidates(expression: str, placeholder: str, *, kind: str) -> tuple[str, ...]:
    base = [placeholder]
    datetime_candidates = [f"{{fmt.date({expression})}}", f"{{fmt.time({expression})}}", f"{{fmt.datetime({expression})}}"]
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
