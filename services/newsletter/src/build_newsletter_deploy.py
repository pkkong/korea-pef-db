#!/usr/bin/env python
"""Deprecated compatibility entrypoint for newsletter-only static builds.

The former monolithic deploy module was moved out of the newsletter service.
Do not add LP, GP, Wiki, or public-site renderer code here. Operators that
still call this path should receive the isolated newsletter bundle builder.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_newsletter_bundle import build_newsletter_bundle, main  # noqa: F401,E402


if __name__ == "__main__":
    raise SystemExit(main())
