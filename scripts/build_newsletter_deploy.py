#!/usr/bin/env python
"""Compatibility wrapper for the newsletter-only bundle builder.

This path used to import the old monolithic deploy module. Keep the command
available for operators, but route it to the isolated newsletter builder so a
newsletter deploy cannot pull LP, GP, Wiki, or legacy public-site code.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_newsletter_bundle import build_newsletter_bundle, main  # noqa: F401,E402


if __name__ == "__main__":
    raise SystemExit(main())
