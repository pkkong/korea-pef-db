"""Vercel entrypoint for the standalone newsletter app."""

try:
    from .app import app  # type: ignore  # noqa: F401
except ImportError:
    from app import app  # type: ignore  # noqa: F401
