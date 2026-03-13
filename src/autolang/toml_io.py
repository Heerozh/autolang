from __future__ import annotations

import json
import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


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

    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)}


def write_string_table(path: str, entries: dict[str, str]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    lines = [
        f"{json.dumps(key, ensure_ascii=False)} = {json.dumps(value, ensure_ascii=False)}"
        for key, value in sorted(entries.items())
        if isinstance(key, str) and isinstance(value, str)
    ]

    with open(path, "w", encoding="utf-8", newline="\n") as file:
        if lines:
            file.write("\n".join(lines))
            file.write("\n")
