"""CLI entrypoint for autolang."""

from __future__ import annotations

import os
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence

from autolang.commands.init import run as run_init
from autolang.commands.sync import run as run_sync
from autolang.commands.translate import run as run_translate

CommandHandler = Callable[[Namespace], int]


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="autolang",
        description="CLI utilities for gettext/Babel/OpenAI-compatible translation flows.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    _register_command(
        subparsers,
        name="init",
        help_text="Initialize project configuration and translation assets.",
        handler=run_init,
    )
    _register_command(
        subparsers,
        name="sync",
        help_text="Sync gettext/Babel catalog files.",
        handler=run_sync,
    )
    _register_command(
        subparsers,
        name="translate",
        help_text="Translate pending catalog entries through a compatible API.",
        handler=run_translate,
    )
    return parser


def _register_command(
    subparsers,
    *,
    name: str,
    help_text: str,
    handler: CommandHandler,
) -> None:
    command_parser = subparsers.add_parser(name, help=help_text)
    if name == "init":
        _configure_init_parser(command_parser)
    elif name == "sync":
        _configure_sync_parser(command_parser)
    elif name == "translate":
        _configure_translate_parser(command_parser)
    command_parser.set_defaults(handler=handler)


def _configure_init_parser(command_parser: ArgumentParser) -> None:
    command_parser.add_argument(
        "-d",
        "--directory",
        default="locales",
        help="Directory used to store POT and PO files.",
    )
    command_parser.add_argument(
        "-l",
        "--locale",
        dest="locales",
        action="append",
        required=True,
        help="Target locale to initialize. Repeat for multiple locales.",
    )
    command_parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        required=True,
        help="Source path to scan for gettext messages. Repeat for multiple paths.",
    )


def _configure_sync_parser(command_parser: ArgumentParser) -> None:
    command_parser.add_argument(
        "-d",
        "--directory",
        default="locales",
        help="Directory used to store POT and PO files.",
    )
    command_parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        required=True,
        help="Source path to scan for gettext messages. Repeat for multiple paths.",
    )


def _configure_translate_parser(command_parser: ArgumentParser) -> None:
    command_parser.add_argument(
        "-d",
        "--directory",
        default="locales",
        help="Directory used to store POT and PO files.",
    )
    command_parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        required=True,
        help="Source path hint used to scope translation batches by file.",
    )
    command_parser.add_argument(
        "--model",
        default=os.environ.get("AUTOLANG_MODEL") or os.environ.get("OPENAI_MODEL"),
        help="Model name. Defaults to AUTOLANG_MODEL or OPENAI_MODEL.",
    )
    command_parser.add_argument(
        "--base-url",
        dest="base_url",
        default=(
            os.environ.get("AUTOLANG_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
        ),
        help="OpenAI-compatible API base URL. Defaults to AUTOLANG_BASE_URL or OPENAI_BASE_URL.",
    )
    command_parser.add_argument(
        "--api-key",
        dest="api_key",
        default=os.environ.get("AUTOLANG_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        help="API key. Defaults to AUTOLANG_API_KEY or OPENAI_API_KEY.",
    )
    command_parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Maximum untranslated entries to send in one model request.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler: CommandHandler = args.handler
    return handler(args)
