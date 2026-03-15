from __future__ import annotations

import json
import os
import tomllib

_ENTRY_SEPARATOR = "# --------------------"


def load_string_table(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "rb") as file:
            data = tomllib.load(file)
    except OSError:
        return {}
    except tomllib.TOMLDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        key: value
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _dump_multiline_basic_toml_string(value: str) -> str:
    parts: list[str] = []
    for char in value:
        if char == "\\":
            parts.append("\\\\")
        elif char == '"':
            parts.append('\\"')
        elif char == "\b":
            parts.append("\\b")
        elif char == "\t":
            parts.append("\\t")
        elif char == "\n":
            parts.append("\n")
        elif char == "\f":
            parts.append("\\f")
        elif char == "\r":
            parts.append("\\r")
        else:
            codepoint = ord(char)
            if codepoint < 0x20 or codepoint == 0x7F:
                parts.append(f"\\u{codepoint:04x}")
            else:
                parts.append(char)
    return f'"""\n{"".join(parts)}"""'


def write_string_table(path: str, entries: dict[str, str]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    lines = [
        (
            f"{json.dumps(key, ensure_ascii=False)} = "
            f"{_dump_multiline_basic_toml_string(value)}\n{_ENTRY_SEPARATOR}"
        )
        for key, value in sorted(entries.items())
        if isinstance(key, str) and isinstance(value, str)
    ]

    with open(path, "w", encoding="utf-8", newline="\n") as file:
        if lines:
            file.write("\n".join(lines))
            file.write("\n")
