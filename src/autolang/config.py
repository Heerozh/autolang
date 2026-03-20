"""Runtime configuration helpers for autolang."""

from __future__ import annotations

import os


def get_domain() -> str:
    """Return the gettext domain used across the project."""
    return os.environ.get("DEFAULT_DOMAIN", "messages")
