#!/usr/bin/env python
"""Compatibility import for common daily-news helpers.

The implementation lives in ``services.shared.src.daily_news_common`` so LP,
GP, and newsletter code can share the same utilities without importing from a
different service's private folder.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.shared.src.daily_news_common import *  # noqa: F401,F403,E402
