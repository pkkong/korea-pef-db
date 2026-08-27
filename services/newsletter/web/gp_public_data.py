"""Read the published GP page snapshot from Supabase for the Vercel runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PUBLIC_PAGE_NAMES = {"market.html", "gps.html"}
GP_DETAIL_PAGE_RE = re.compile(r"gp-[0-9]+\.html")


class GPPublicDataError(RuntimeError):
    pass


def _supabase_config() -> tuple[str, str]:
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not base_url or not key:
        raise GPPublicDataError("Supabase public GP read-model credentials are missing")
    return base_url, key


def _request_json(url: str, key: str) -> Any:
    request = Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_active_gp_page(page_name: str) -> dict[str, str]:
    if page_name not in PUBLIC_PAGE_NAMES and not GP_DETAIL_PAGE_RE.fullmatch(page_name):
        raise GPPublicDataError(f"Unsupported GP page: {page_name}")
    base_url, key = _supabase_config()
    snapshot_query = urlencode(
        {
            "select": "snapshot_id,reporting_period,as_of_date,source_sha256",
            "status": "eq.published",
            "order": "published_at.desc",
            "limit": "1",
        }
    )
    snapshots = _request_json(f"{base_url}/rest/v1/gp_public_snapshots?{snapshot_query}", key)
    if not isinstance(snapshots, list) or not snapshots or not isinstance(snapshots[0], dict):
        raise GPPublicDataError("No published GP snapshot is available")
    snapshot = snapshots[0]
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    if not snapshot_id:
        raise GPPublicDataError("Published GP snapshot id is missing")

    page_query = urlencode(
        {
            "select": "page_html,content_sha256",
            "snapshot_id": f"eq.{snapshot_id}",
            "page_path": f"eq.{page_name}",
            "limit": "1",
        }
    )
    pages = _request_json(f"{base_url}/rest/v1/gp_public_pages?{page_query}", key)
    if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
        raise GPPublicDataError(f"Published GP snapshot is missing {page_name}")
    page = pages[0]
    page_html = str(page.get("page_html") or "")
    content_sha256 = str(page.get("content_sha256") or "")
    if not page_html or not content_sha256:
        raise GPPublicDataError(f"Published GP page payload is incomplete: {page_name}")
    actual_sha256 = hashlib.sha256(page_html.encode("utf-8")).hexdigest()
    if actual_sha256 != content_sha256:
        raise GPPublicDataError(f"Published GP page hash does not match: {page_name}")
    return {
        "page_html": page_html,
        "snapshot_id": snapshot_id,
        "reporting_period": str(snapshot.get("reporting_period") or ""),
        "as_of_date": str(snapshot.get("as_of_date") or ""),
        "source_sha256": str(snapshot.get("source_sha256") or ""),
    }
