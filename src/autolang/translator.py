"""OpenAI-compatible translation client used by autolang."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


DEFAULT_SYSTEM_PROMPT = """You are a translation engine for gettext strings in a Python project.

Translate every input string into the requested target language.
The source language is unknown and individual strings may contain mixed languages. Do not ask for the source language and do not preserve the original language on purpose. Always produce a final translation in the target language.

Preserve placeholders and technical content exactly unless the surrounding natural language must change:
- Python/Babel placeholders such as {name}, {value:.2f}, %(count)s, %s, and format-like tokens
- Markup, code spans, CLI flags, file paths, environment variables, and API/class/function names
- Project and product names such as Autolang
- Line breaks and meaningful whitespace

When a string is already fully appropriate for the target language, keep it unchanged.
Return strict JSON only, with the shape {"translations":[{"index":0,"text":"..."}]} and no extra prose."""


class TranslatorError(RuntimeError):
    """Base error raised by the translator client."""


class TranslatorHTTPError(TranslatorError):
    """Raised when the remote API request fails."""


class TranslatorResponseError(TranslatorError):
    """Raised when the model response is malformed."""


@dataclass(frozen=True, slots=True)
class TranslationInput:
    """Single text entry to translate."""

    text: str
    context: str | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationOutput:
    """Single translated text entry."""

    text: str


@dataclass(frozen=True, slots=True)
class ReferenceTranslation:
    """Already translated text used as context for the current batch."""

    source_text: str
    translated_text: str
    context: str | None = None


class OpenAITranslator:
    """Thin OpenAI-compatible client for batched translation requests."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        system_prompt: str | None = None,
        timeout: float = 60.0,
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.temperature = temperature

    def translate_batch(
        self,
        *,
        target_language: str,
        entries: list[TranslationInput],
        source_file: str | None = None,
        references: list[ReferenceTranslation] | None = None,
    ) -> list[TranslationOutput]:
        """Translate a batch of strings into the target language."""
        if not entries:
            return []

        payload = self.build_payload(
            target_language=target_language,
            entries=entries,
            source_file=source_file,
            references=references,
        )
        response_data = self._post_json(payload)
        return self._parse_outputs(response_data, expected_count=len(entries))

    def build_payload(
        self,
        *,
        target_language: str,
        entries: list[TranslationInput],
        source_file: str | None = None,
        references: list[ReferenceTranslation] | None = None,
    ) -> dict[str, object]:
        """Build the chat completions payload for a translation batch."""
        return {
            "model": self.model,
            "temperature": self.temperature,
            "messages": self.build_messages(
                target_language=target_language,
                entries=entries,
                source_file=source_file,
                references=references,
            ),
        }

    def build_messages(
        self,
        *,
        target_language: str,
        entries: list[TranslationInput],
        source_file: str | None = None,
        references: list[ReferenceTranslation] | None = None,
    ) -> list[dict[str, str]]:
        """Build chat messages for the current translation batch."""
        messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        prompt_body = {
            "task": "translate_gettext_batch",
            "target_language": target_language,
            "source_file": source_file,
            "entries": [
                {
                    "index": index,
                    "text": entry.text,
                    "context": entry.context,
                    "comment": entry.comment,
                }
                for index, entry in enumerate(entries)
            ],
            "reference_translations": [
                {
                    "source_text": reference.source_text,
                    "translated_text": reference.translated_text,
                    "context": reference.context,
                }
                for reference in (references or [])
            ],
            "instructions": [
                "Translate each entry into the target language.",
                "The source language may be mixed or unknown inside a single string.",
                "Preserve placeholders, formatting tokens, code, and technical identifiers exactly.",
                "Use the provided reference translations only as style and terminology context.",
                "Return JSON only with the same indexes in the same order.",
            ],
            "response_schema": {
                "translations": [
                    {
                        "index": 0,
                        "text": "translated text",
                    }
                ]
            },
        }
        messages.append(
            {
                "role": "user",
                "content": json.dumps(prompt_body, ensure_ascii=False, indent=2),
            }
        )
        return messages

    def _post_json(self, payload: dict[str, object]) -> dict[str, Any]:
        endpoint = self._chat_completions_url()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        http_request = request.Request(
            endpoint,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise TranslatorHTTPError(
                f"Translation request failed with HTTP {exc.code}: {details}"
            ) from exc
        except error.URLError as exc:
            raise TranslatorHTTPError(
                f"Translation request failed: {exc.reason}"
            ) from exc

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise TranslatorResponseError("Translation API returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise TranslatorResponseError("Translation API response must be a JSON object.")
        return data

    def _parse_outputs(
        self,
        response_data: dict[str, Any],
        *,
        expected_count: int,
    ) -> list[TranslationOutput]:
        content = self._extract_message_content(response_data)
        response_json = self._load_response_json(content)

        raw_translations = response_json.get("translations")
        if not isinstance(raw_translations, list):
            raise TranslatorResponseError("Model response must contain a translations list.")
        if len(raw_translations) != expected_count:
            raise TranslatorResponseError(
                "Model response count does not match the number of requested entries."
            )

        outputs: list[TranslationOutput] = []
        for index, item in enumerate(raw_translations):
            if not isinstance(item, dict):
                raise TranslatorResponseError("Each translation item must be an object.")
            if item.get("index") != index:
                raise TranslatorResponseError(
                    "Model response indexes must match the original request order."
                )
            text = item.get("text")
            if not isinstance(text, str):
                raise TranslatorResponseError("Each translation item must contain text.")
            outputs.append(TranslationOutput(text=text))
        return outputs

    def _extract_message_content(self, response_data: dict[str, Any]) -> str:
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise TranslatorResponseError("Translation API response is missing choices.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise TranslatorResponseError("Translation API response choice is invalid.")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise TranslatorResponseError("Translation API response is missing a message.")

        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            joined = "".join(text_parts)
            if joined:
                return joined

        raise TranslatorResponseError("Translation API message content is missing text.")

    def _load_response_json(self, content: str) -> dict[str, Any]:
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end < start:
                raise TranslatorResponseError("Model response did not contain JSON.")
            try:
                decoded = json.loads(content[start : end + 1])
            except json.JSONDecodeError as exc:
                raise TranslatorResponseError("Model response did not contain valid JSON.") from exc

        if not isinstance(decoded, dict):
            raise TranslatorResponseError("Model response JSON must be an object.")
        return decoded

    def _chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"
