from __future__ import annotations

import argparse

from . import init as _init
from . import sync as _sync
from . import translate as _translate
from .i18n import tt

BatchTranslationItem = _translate.BatchTranslationTarget
BatchTranslationTarget = _translate.BatchTranslationTarget
BatchTranslationOutcome = _translate.BatchTranslationOutcome
BatchTranslationRequest = _translate.BatchTranslationRequest
OpenAICompatibleClient = _translate.OpenAICompatibleClient
PlaceholderSpec = _translate.PlaceholderSpec
TranslationResult = _translate.TranslationResult
TranslationTask = _translate.TranslationTask
validate_translated_text = _translate.validate_translated_text


def handle_translate_command(args: argparse.Namespace) -> int:
    return _translate.handle_translate_command(
        args,
        client_class=OpenAICompatibleClient,
    )


def handle_sync_command(args: argparse.Namespace) -> int:
    return _sync.handle_sync_command(args)


def handle_init_command(args: argparse.Namespace) -> int:
    return _init.handle_init_command(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tt", description=tt("Autolang developer tools.")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    translate_parser = subparsers.add_parser(
        "translate",
        help=tt(
            "Translate the missing text in all locale TOML language files "
            "through an OpenAI-compatible API."
        ),
    )
    translate_parser.add_argument("--source", default="./src/")
    translate_parser.add_argument("--locale-dir", default="locales")
    translate_parser.add_argument("--model", default=None)
    translate_parser.add_argument("--base-url", default=None)
    translate_parser.add_argument("--api-key", default=None)
    translate_parser.add_argument("--timeout", type=float, default=60.0)
    translate_parser.add_argument("--workers", type=int, default=4)
    translate_parser.add_argument("--batch-size", type=int, default=20)
    translate_parser.add_argument("--overwrite", action="store_true")
    translate_parser.add_argument("--dry-run", action="store_true")
    translate_parser.set_defaults(handler=handle_translate_command)

    sync_parser = subparsers.add_parser(
        "sync",
        help=tt("Scan project, Sync the tt()-wrapped text, to all locale TOML files."),
    )
    sync_parser.add_argument("--source", default="./src/")
    sync_parser.add_argument("--locale-dir", default="locales")
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.set_defaults(handler=handle_sync_command)

    init_parser = subparsers.add_parser(
        "init",
        help=tt(
            "Create new TOML files for specified locales, and collect tt()-wrapped text templates."
        ),
    )
    init_parser.add_argument("--source", default="./src/")
    init_parser.add_argument("--locale-dir", default="locales")
    init_parser.add_argument("--locales", nargs="+", required=True)
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--dry-run", action="store_true")
    init_parser.set_defaults(handler=handle_init_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


__all__ = [
    "BatchTranslationItem",
    "BatchTranslationTarget",
    "BatchTranslationOutcome",
    "BatchTranslationRequest",
    "OpenAICompatibleClient",
    "PlaceholderSpec",
    "TranslationResult",
    "TranslationTask",
    "build_parser",
    "handle_init_command",
    "handle_sync_command",
    "handle_translate_command",
    "main",
    "validate_translated_text",
]
