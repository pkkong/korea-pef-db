"""Shared public brand asset helpers.

The curated registry currently lives in the newsletter service for historical
compatibility. Cross-service renderers should import this shared facade instead
of reaching into ``services.newsletter.src`` directly.
"""

from __future__ import annotations

from services.newsletter.src.brand_assets import *  # noqa: F401,F403
