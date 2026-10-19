"""Vercel entrypoint for the standalone GP service."""
if __package__:
    from .app import app
else:
    from app import app
