"""Implementation for the `autolang init` command."""

from __future__ import annotations

from argparse import Namespace

from autolang.babel import extract_catalog, init_catalog, locale_catalog_path


def run(args: Namespace) -> int:
    """Initialize locale catalogs from extracted source messages."""
    extract_exit_code = extract_catalog(
        directory=args.directory,
        domain=args.domain,
        sources=args.sources,
    )
    if extract_exit_code != 0:
        return extract_exit_code

    for locale in args.locales:
        catalog = locale_catalog_path(args.directory, locale, args.domain)
        if catalog.exists():
            continue
        init_exit_code = init_catalog(
            directory=args.directory,
            domain=args.domain,
            locale=locale,
        )
        if init_exit_code != 0:
            return init_exit_code

    return 0
