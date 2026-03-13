from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Collection, Generator, Mapping
from typing import Any

from .static_analysis import analyze_static_cues
from ..source_templates import extract_template_from_call


class _TTCallExtractor(ast.NodeVisitor):
    def __init__(self, keywords: Collection[str], static_cues: dict[tuple[int, str], str]):
        self.keywords = set(keywords)
        self.static_cues = static_cues
        self.messages: list[tuple[int, str, str, list[str]]] = []

    def visit_Call(self, node: ast.Call) -> None:
        func_name = _get_keyword_name(node.func, self.keywords)
        if func_name is not None:
            message, _variables = extract_template_from_call(node)
            if message:
                cue_text = self.static_cues.get((node.lineno, message))
                comments = [cue_text] if cue_text else []
                self.messages.append((node.lineno, func_name, message, comments))

        self.generic_visit(node)


def extract_tt_python(
    fileobj,
    keywords: Collection[str],
    comment_tags: Collection[str],
    options: Mapping[str, Any],
) -> Generator[tuple[int, str, str, list[str]], None, None]:
    del comment_tags

    source = _read_python_source(fileobj, options)
    if source is None:
        return

    try:
        module = ast.parse(source)
    except SyntaxError:
        return

    static_cues = {
        (item.line, item.template): item.cue_text
        for item in analyze_static_cues(source, filename=str(options.get("filename") or ""))
    }
    extractor = _TTCallExtractor(keywords or {"tt"}, static_cues)
    extractor.visit(module)

    for message in extractor.messages:
        yield message


def _get_keyword_name(node: ast.AST, keywords: set[str]) -> str | None:
    if isinstance(node, ast.Name) and node.id in keywords:
        return node.id
    return None


def _read_python_source(fileobj, options: Mapping[str, Any]) -> str | None:
    data = fileobj.read()
    if not data:
        return None

    if isinstance(data, str):
        return data

    fallback_encoding = str(options.get("encoding", "utf-8"))
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except SyntaxError:
        encoding = fallback_encoding

    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return data.decode(fallback_encoding, errors="replace")
