"""Unit tests for the OpenAI-compatible translator client."""

from __future__ import annotations

import json
from io import BytesIO

import pytest

from autolang.translator import (
    DEFAULT_SYSTEM_PROMPT,
    OpenAITranslator,
    ReferenceTranslation,
    TranslationInput,
    TranslationOutput,
    TranslatorResponseError,
)


def test_build_messages_include_default_and_custom_system_prompts() -> None:
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
        api_key="secret",
        system_prompt="Project-specific glossary goes here.",
    )

    messages = translator.build_messages(
        target_language="zh",
        source_file="app.py",
        entries=[TranslationInput(text="Hello {name}")],
        references=[
            ReferenceTranslation(
                source_text="Save",
                translated_text="保存",
                context="button_label",
            ),
            ReferenceTranslation(
                source_text="{count} file",
                plural_source_text="{count} files",
                translated_plural_texts=["{count} 个文件"],
                context="status_line",
            ),
        ],
    )

    assert messages[0] == {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}
    assert messages[1] == {
        "role": "system",
        "content": "Project-specific glossary goes here.",
    }
    assert messages[2]["role"] == "user"
    prompt = json.loads(messages[2]["content"])
    assert prompt["target_language"] == "zh [中文]"
    assert prompt["source_file"] == "app.py"
    assert prompt["entries"] == [
        {
            "index": 0,
            "kind": "singular",
            "text": "Hello {name}",
            "context": None,
            "comment": None,
        }
    ]
    assert prompt["reference_translations"] == [
        {
            "kind": "singular",
            "text": "Save",
            "translation": "保存",
            "context": "button_label",
        },
        {
            "kind": "plural",
            "singular_text": "{count} file",
            "plural_text": "{count} files",
            "plural_translations": ["{count} 个文件"],
            "context": "status_line",
        },
    ]


def test_translate_batch_parses_json_response() -> None:
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
    )

    def fake_post_json(payload: dict[str, object]) -> dict[str, object]:
        assert payload["model"] == "gpt-test"
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "translations": [
                                    {"index": 0, "text": "你好 {name}"},
                                    {"index": 1, "text": "欢迎"},
                                ]
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    translator._post_json = fake_post_json  # type: ignore[method-assign]

    outputs = translator.translate_batch(
        target_language="zh",
        source_file="app.py",
        entries=[
            TranslationInput(text="Hello {name}"),
            TranslationInput(text="Welcome"),
        ],
    )

    assert [output.text for output in outputs] == ["你好 {name}", "欢迎"]


def test_translate_batch_parses_plural_json_response() -> None:
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
    )

    translator._post_json = lambda payload: {  # type: ignore[method-assign]
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "translations": [
                                {
                                    "index": 0,
                                    "plural_texts": [
                                        "{count} файл",
                                        "{count} файла",
                                        "{count} файлов",
                                    ],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    outputs = translator.translate_batch(
        target_language="ru",
        entries=[
            TranslationInput(
                text="{count} file",
                plural_text="{count} files",
                expected_plural_forms=3,
            )
        ],
    )

    assert outputs == [
        TranslationOutput(
            plural_texts=[
                "{count} файл",
                "{count} файла",
                "{count} файлов",
            ]
        )
    ]


def test_translate_batch_accepts_json_wrapped_in_extra_text() -> None:
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
    )

    translator._post_json = lambda payload: {  # type: ignore[method-assign]
        "choices": [
            {
                "message": {
                    "content": (
                        'Result:\n{"translations":[{"index":0,"text":"简体中文"}]}'
                    )
                }
            }
        ]
    }

    outputs = translator.translate_batch(
        target_language="zh",
        entries=[TranslationInput(text="Mixed English 中文")],
    )

    assert [output.text for output in outputs] == ["简体中文"]


@pytest.mark.parametrize(
    ("response_data", "reason"),
    [
        (
            {
                "choices": [
                    {
                        "message": {"content": '{"translation":"مرحبا"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
            "Model response must contain a translations list.",
        ),
        (
            {"choices": [{"message": {"content": '{"translations":null}'}}]},
            "Model response must contain a translations list.",
        ),
        (
            {"choices": [{"message": {"content": "无法完成翻译"}}]},
            "Model response did not contain JSON.",
        ),
        (
            {"error": {"message": "服务暂不可用"}},
            "Translation API response is missing choices.",
        ),
    ],
)
def test_translate_batch_includes_response_in_parse_errors(
    monkeypatch: pytest.MonkeyPatch, response_data: dict[str, object], reason: str
) -> None:
    monkeypatch.setattr("autolang.translator._", lambda message: message)
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
        api_key="secret-api-key",
    )
    translator._post_json = lambda payload: response_data  # type: ignore[method-assign]

    with pytest.raises(TranslatorResponseError) as exc_info:
        translator.translate_batch(
            target_language="ar",
            entries=[TranslationInput(text="Hello")],
        )

    message = str(exc_info.value)
    assert message.startswith(reason)
    assert "Translation API response:\n" in message
    assert json.dumps(response_data, ensure_ascii=False, indent=2) in message
    assert "secret-api-key" not in message


@pytest.mark.parametrize(
    ("response_body", "reason"),
    [
        ("<html>服务暂不可用</html>", "Translation API returned invalid JSON."),
        ('["unexpected response"]', "Translation API response must be a JSON object."),
    ],
)
def test_translate_batch_includes_invalid_api_response(
    monkeypatch: pytest.MonkeyPatch, response_body: str, reason: str
) -> None:
    monkeypatch.setattr("autolang.translator._", lambda message: message)
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
    )
    monkeypatch.setattr(
        "autolang.translator.request.urlopen",
        lambda *args, **kwargs: BytesIO(response_body.encode("utf-8")),
    )

    with pytest.raises(TranslatorResponseError) as exc_info:
        translator.translate_batch(
            target_language="zh",
            entries=[TranslationInput(text="Hello")],
        )

    assert str(exc_info.value).startswith(reason)
    assert str(exc_info.value).endswith(f"Translation API response:\n{response_body}")


@pytest.mark.parametrize(
    ("locale", "entry", "response_item", "expected"),
    [
        (
            "zh_Hant",
            TranslationInput(text="{cname}.{pname}不是字符串属性（dtype={d}）"),
            {"index": 0, "text": "{cname}.{pname}不是字串屬性（dtype={d}）"},
            TranslationOutput(text="{cname}.{pname}不是字串屬性（dtype={d}）"),
        ),
        (
            "en",
            TranslationInput(
                text="{count} file",
                plural_text="{count} files",
                expected_plural_forms=2,
            ),
            {"index": 0, "plural_texts": ["{count} file", "{count} files"]},
            TranslationOutput(plural_texts=["{count} file", "{count} files"]),
        ),
    ],
)
def test_translate_batch_accepts_single_object_response(
    locale: str,
    entry: TranslationInput,
    response_item: dict[str, object],
    expected: TranslationOutput,
) -> None:
    translator = OpenAITranslator(model="gpt-test", base_url="https://example.com/v1")
    translator._post_json = lambda payload: {  # type: ignore[method-assign]
        "choices": [
            {"message": {"content": json.dumps(response_item, ensure_ascii=False)}}
        ]
    }

    assert translator.translate_batch(target_language=locale, entries=[entry]) == [
        expected
    ]


@pytest.mark.parametrize(
    ("plural", "entry_count", "response_item"),
    [
        (False, 2, {"index": 0, "text": "Hello"}),
        (False, 1, {"text": "Hello"}),
        (False, 1, {"index": 9, "text": "Hello"}),
        (False, 1, {"index": "0", "text": "Hello"}),
        (False, 1, {"index": 0}),
        (False, 1, {"index": 0, "text": 42}),
        (False, 1, {"index": 0, "text": "Hello", "translations": None}),
        (False, 1, {"index": 0, "text": "Hello", "translations": []}),
        (True, 1, {"index": 0, "text": "file"}),
        (True, 1, {"index": 0, "plural_texts": "files"}),
        (True, 1, {"index": 0, "plural_texts": ["file"]}),
        (True, 1, {"index": 0, "plural_texts": ["file", 42]}),
    ],
)
def test_single_object_fallback_preserves_validation(
    plural: bool, entry_count: int, response_item: dict[str, object]
) -> None:
    translator = OpenAITranslator(model="gpt-test", base_url="https://example.com/v1")
    translator._post_json = lambda payload: {  # type: ignore[method-assign]
        "choices": [{"message": {"content": json.dumps(response_item)}}]
    }
    entry = TranslationInput(
        text="file",
        plural_text="files" if plural else None,
        expected_plural_forms=2 if plural else None,
    )

    with pytest.raises(TranslatorResponseError):
        translator.translate_batch(target_language="en", entries=[entry] * entry_count)


def test_translate_batch_rejects_mismatched_indexes() -> None:
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
    )

    translator._post_json = lambda payload: {  # type: ignore[method-assign]
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"translations": [{"index": 9, "text": "你好"}]},
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    with pytest.raises(TranslatorResponseError):
        translator.translate_batch(
            target_language="zh",
            entries=[TranslationInput(text="Hello")],
        )


def test_translate_batch_rejects_wrong_plural_form_count() -> None:
    translator = OpenAITranslator(
        model="gpt-test",
        base_url="https://example.com/v1",
    )

    translator._post_json = lambda payload: {  # type: ignore[method-assign]
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "translations": [
                                {
                                    "index": 0,
                                    "plural_texts": ["{count} file"],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    with pytest.raises(TranslatorResponseError):
        translator.translate_batch(
            target_language="en",
            entries=[
                TranslationInput(
                    text="{count} file",
                    plural_text="{count} files",
                    expected_plural_forms=2,
                )
            ],
        )
