"""Implementation for the `autolang sync` command."""

from __future__ import annotations

from argparse import Namespace

from autolang.babel import discover_locales, extract_catalog, update_catalogs


def run(args: Namespace) -> int:
    """Sync locale catalogs with the latest extracted source messages."""
    locales = discover_locales(args.directory)

    extract_exit_code = extract_catalog(
        directory=args.directory,
        domain=args.domain,
        sources=args.sources,
    )
    if extract_exit_code != 0:
        return extract_exit_code

    return update_catalogs(
        directory=args.directory,
        domain=args.domain,
        locales=locales,
    )
