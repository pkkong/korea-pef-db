#!/usr/bin/env python
"""Compatibility wrapper for newsletter no-network checks."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.tests.test_daily_news_logic import *  # noqa: F401,F403,E402
from services.newsletter.tests.test_daily_news_logic import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
