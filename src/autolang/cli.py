"""CLI entrypoint for autolang."""

from __future__ import annotations

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
    command_parser.set_defaults(handler=handler)


def _configure_init_parser(command_parser: ArgumentParser) -> None:
    command_parser.add_argument(
        "-d",
        "--directory",
        default="locales",
        help="Directory used to store POT and PO files.",
    )
    command_parser.add_argument(
        "-D",
        "--domain",
        default="messages",
        help="Catalog domain name.",
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
        "-D",
        "--domain",
        default="messages",
        help="Catalog domain name.",
    )
    command_parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        required=True,
        help="Source path to scan for gettext messages. Repeat for multiple paths.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler: CommandHandler = args.handler
    return handler(args)
