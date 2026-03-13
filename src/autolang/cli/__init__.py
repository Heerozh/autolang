from __future__ import annotations

import argparse

from . import collect as _collect
from . import translate as _translate

BatchTranslationItem = _translate.BatchTranslationItem
BatchTranslationOutcome = _translate.BatchTranslationOutcome
BatchTranslationRequest = _translate.BatchTranslationRequest
OpenAICompatibleClient = _translate.OpenAICompatibleClient
PlaceholderSpec = _translate.PlaceholderSpec
TranslationResult = _translate.TranslationResult
TranslationTask = _translate.TranslationTask
validate_translated_text = _translate.validate_translated_text


def handle_translate_command(args: argparse.Namespace) -> int:
    _translate.OpenAICompatibleClient = OpenAICompatibleClient
    return _translate.handle_translate_command(args)


def handle_collect_command(args: argparse.Namespace) -> int:
    return _collect.handle_collect_command(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tt", description="Autolang developer tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    translate_parser = subparsers.add_parser(
        "translate",
        help="Translate locale TOML files through an OpenAI-compatible API.",
    )
    translate_parser.add_argument("--locale-dir", default="locales")
    translate_parser.add_argument("--source-locale", default="en")
    translate_parser.add_argument("--target-locales", nargs="*", default=None)
    translate_parser.add_argument("--source-language", default=None)
    translate_parser.add_argument("--model", default=None)
    translate_parser.add_argument("--base-url", default=None)
    translate_parser.add_argument("--api-key", default=None)
    translate_parser.add_argument("--timeout", type=float, default=60.0)
    translate_parser.add_argument("--workers", type=int, default=4)
    translate_parser.add_argument("--batch-size", type=int, default=20)
    translate_parser.add_argument("--overwrite", action="store_true")
    translate_parser.add_argument("--dry-run", action="store_true")
    translate_parser.set_defaults(handler=handle_translate_command)

    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect tt()-wrapped source templates into the source locale TOML file.",
    )
    collect_parser.add_argument("--source", default=".")
    collect_parser.add_argument("--locale-dir", default="locales")
    collect_parser.add_argument("--source-locale", default="en")
    collect_parser.add_argument("--dry-run", action="store_true")
    collect_parser.set_defaults(handler=handle_collect_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


__all__ = [
    "BatchTranslationItem",
    "BatchTranslationOutcome",
    "BatchTranslationRequest",
    "OpenAICompatibleClient",
    "PlaceholderSpec",
    "TranslationResult",
    "TranslationTask",
    "build_parser",
    "handle_collect_command",
    "handle_translate_command",
    "main",
    "validate_translated_text",
]
