#!/usr/bin/env python
"""Compatibility import for the newsletter service common helpers."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.newsletter.src.daily_news_common import *  # noqa: F401,F403,E402
