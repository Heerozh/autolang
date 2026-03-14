from __future__ import annotations

import atexit
import json
import queue
import re
import subprocess
import threading
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any

_TYPE_PATTERN = re.compile(r"^\([^)]*\)\s+[^\n:]+:\s*(.+)$")
_SESSION_LOCK = threading.Lock()
_SESSIONS: dict[Path, "_PyrightSession"] = {}


@dataclass(slots=True)
class _DocumentState:
    version: int
    text: str


class _PyrightStreamReader(threading.Thread):
    def __init__(
        self,
        stream,
        output_queue: "queue.Queue[dict[str, Any] | BaseException | None]",
    ) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._output_queue = output_queue

    def run(self) -> None:
        try:
            while True:
                message = self._read_message()
                if message is None:
                    self._output_queue.put(None)
                    return
                self._output_queue.put(message)
        except BaseException as exc:  # pragma: no cover - defensive transport guard
            self._output_queue.put(exc)

    def _read_message(self) -> dict[str, Any] | None:
        headers: list[bytes] = []
        while True:
            line = self._stream.readline()
            if not line:
                return None
            if line == b"\r\n":
                break
            headers.append(line)

        content_length = 0
        for header in headers:
            name, _, value = header.decode("ascii").partition(":")
            if name.lower() == "content-length":
                content_length = int(value.strip())
                break

        if content_length <= 0:
            return None

        payload = self._stream.read(content_length)
        if not payload:
            return None
        return json.loads(payload.decode("utf-8"))


class _PyrightSession:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._documents: dict[str, _DocumentState] = {}
        self._messages: "queue.Queue[dict[str, Any] | BaseException | None]" = (
            queue.Queue()
        )
        self._request_ids = count(1)
        self._write_lock = threading.Lock()
        self._proc = subprocess.Popen(
            ["basedpyright-langserver", "--stdio"],
            cwd=str(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Unable to start basedpyright language server")

        self._stdin = self._proc.stdin
        self._reader = _PyrightStreamReader(self._proc.stdout, self._messages)
        self._reader.start()
        self._initialize()

    def close(self) -> None:
        if self._proc.poll() is not None:
            return
        try:
            self._notify("exit", {})
        except Exception:
            pass
        self._proc.kill()
        self._proc.wait(timeout=1)

    def open_document(self, path: Path, text: str) -> None:
        uri = path.resolve().as_uri()
        state = self._documents.get(uri)
        if state is None:
            self._documents[uri] = _DocumentState(version=1, text=text)
            self._notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "python",
                        "version": 1,
                        "text": text,
                    }
                },
            )
            return

        if state.text == text:
            return

        state.version += 1
        state.text = text
        self._notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": state.version},
                "contentChanges": [{"text": text}],
            },
        )

    def hover_type(self, path: Path, line: int, col: int) -> str | None:
        response = self._request(
            "textDocument/hover",
            {
                "textDocument": {"uri": path.resolve().as_uri()},
                "position": {"line": line - 1, "character": col},
            },
        )
        if not isinstance(response, dict):
            return None

        contents = response.get("contents")
        text = _contents_to_text(contents)
        if not text:
            return None

        first_line = text.splitlines()[0].strip()
        match = _TYPE_PATTERN.match(first_line)
        if match is None:
            return None
        return match.group(1).strip()

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "processId": None,
                "rootUri": self._root.resolve().as_uri(),
                "capabilities": {},
                "clientInfo": {"name": "autolang"},
            },
        )
        self._notify("initialized", {})

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        request_id = next(self._request_ids)
        self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        while True:
            message = self._messages.get(timeout=10)
            if message is None:
                return None
            if isinstance(message, BaseException):
                raise message
            if message.get("id") != request_id:
                continue
            return message.get("result")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._write_lock:
            self._stdin.write(header)
            self._stdin.write(body)
            self._stdin.flush()


def infer_type(
    *,
    source: str,
    filename: str | None,
    line: int,
    col: int,
) -> str | None:
    try:
        document_path = _document_path(filename=filename, source=source)
        session = _get_session(_project_root(document_path))
        session.open_document(document_path, source)
        return session.hover_type(document_path, line, col)
    except Exception as e:
        print(
            "ERROR: Failed to infer type, please add autolang[cli] to dev dependence, "
            "otherwise translation will not accurate:" + str(e)
        )
        return None


def _get_session(root: Path) -> _PyrightSession:
    resolved_root = root.resolve()
    with _SESSION_LOCK:
        session = _SESSIONS.get(resolved_root)
        if session is None:
            session = _PyrightSession(resolved_root)
            _SESSIONS[resolved_root] = session
        return session


def _project_root(filename: Path) -> Path:
    candidates = [filename.parent, *filename.parent.parents]
    markers = ("pyproject.toml", "pyrightconfig.json", "basedpyright.json", ".git")
    for candidate in candidates:
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return Path.cwd()


def _document_path(*, filename: str | None, source: str) -> Path:
    if filename:
        return Path(filename).resolve()

    digest = str(abs(hash(source)))
    return (Path.cwd() / ".autolang-pyright" / f"inline-{digest}.py").resolve()


def _contents_to_text(contents: Any) -> str:
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        value = contents.get("value")
        return value if isinstance(value, str) else ""
    if isinstance(contents, list):
        parts = [_contents_to_text(item) for item in contents]
        return "\n".join(part for part in parts if part)
    return ""


def _close_sessions() -> None:
    with _SESSION_LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    for session in sessions:
        session.close()


atexit.register(_close_sessions)
