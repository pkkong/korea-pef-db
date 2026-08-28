#!/usr/bin/env python3
"""Publish a verified GP static snapshot to the Supabase public read model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_fss_statistics_ready import (  # noqa: E402
    DEFAULT_DB,
    DEFAULT_REGISTRY,
    check_fss_statistics,
    latest_registry_row,
    read_registry,
    sha256_file,
)


DEFAULT_SITE_DIR = REPO_ROOT / "services" / "newsletter" / "deploy" / "site"
DEFAULT_PAYLOAD_OUT = REPO_ROOT / "exports" / "gp" / "gp_public_snapshot.json"
CORE_PAGE_PATHS = ("market.html", "gps.html")


def public_page_paths(site_dir: Path) -> tuple[str, ...]:
    detail_pages = tuple(
        sorted(
            path.name
            for path in site_dir.glob("gp-*.html")
            if re.fullmatch(r"gp-[0-9]+\.html", path.name)
        )
    )
    return CORE_PAGE_PATHS + detail_pages
RETRIABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class GPReadModelError(RuntimeError):
    pass


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _supabase_url() -> str:
    value = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not value:
        raise GPReadModelError("SUPABASE_URL is required for --apply")
    return value


def _supabase_key() -> str:
    value = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    if not value:
        raise GPReadModelError("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY is required for --apply")
    return value


def _rest_request(
    resource: str,
    *,
    method: str = "GET",
    query: dict[str, str] | None = None,
    payload: object | None = None,
    prefer: str | None = None,
) -> Any:
    base_url = _supabase_url()
    key = _supabase_key()
    url = f"{base_url}/rest/v1/{resource}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None

    last_error: BaseException | None = None
    for attempt in range(4):
        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in RETRIABLE_HTTP_STATUS_CODES or attempt == 3:
                raise GPReadModelError(f"Supabase {method} {resource} failed: HTTP {exc.code} {detail}") from exc
            last_error = exc
        except (URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt == 3:
                raise GPReadModelError(f"Supabase {method} {resource} failed: {exc}") from exc
            last_error = exc
        time.sleep(min(8.0, 0.75 * (2**attempt)))

    raise GPReadModelError(f"Supabase {method} {resource} failed: {last_error}")


def _content_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot_content_sha256(page_contents: list[tuple[str, str]]) -> str:
    """Return a stable digest for the complete published GP page set."""
    value = "\n".join(f"{page_path}\0{content_sha256}" for page_path, content_sha256 in page_contents)
    return _content_sha256(value)


def _page_declares_reporting_period(page_html: str, expected_period: str) -> bool:
    if expected_period in page_html:
        return True
    for tag in re.findall(r"<meta\b[^>]*>", page_html, flags=re.IGNORECASE):
        name = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", tag, flags=re.IGNORECASE)
        content = re.search(r"\bcontent\s*=\s*['\"]([^'\"]*)['\"]", tag, flags=re.IGNORECASE)
        if name and content and name.group(1).lower() == "kpef-fss-reporting-period":
            return content.group(1) == expected_period
    return False


def _metadata_from_canonical_manifest(path: Path) -> dict[str, object]:
    """Read the FSS identity from Supabase restore output, not local raw files."""
    data = json.loads(path.read_text(encoding="utf-8"))
    source = data.get("snapshot", data)
    if not isinstance(source, dict):
        raise GPReadModelError(f"Canonical snapshot manifest is invalid: {path}")
    required = (
        "reporting_period",
        "as_of_date",
        "source_id",
        "source_sha256",
        "fund_count",
        "primary_gp_count",
        "commitment_amount_krw_mn",
    )
    missing = [field for field in required if source.get(field) in (None, "")]
    if missing:
        raise GPReadModelError(f"Canonical snapshot manifest is missing: {', '.join(missing)}")
    return {field: source[field] for field in required}


def prepare_payload(
    *,
    site_dir: Path,
    db_path: Path,
    registry_path: Path,
    expected_latest_period: str | None = None,
    canonical_manifest: Path | None = None,
) -> dict[str, object]:
    if canonical_manifest:
        metadata = _metadata_from_canonical_manifest(canonical_manifest)
        reporting_period = str(metadata["reporting_period"])
        if expected_latest_period and reporting_period != expected_latest_period:
            raise GPReadModelError(
                "Canonical snapshot reporting period does not match --expected-latest-period: "
                f"{reporting_period} != {expected_latest_period}"
            )
    else:
        readiness = check_fss_statistics(
            db_path=db_path,
            registry_path=registry_path,
            expected_latest_period=expected_latest_period,
        )
        registry_rows = read_registry(registry_path)
        latest = latest_registry_row(registry_rows, str(readiness["latest_period"]))
        raw_path = REPO_ROOT / latest["local_file"]
        metadata = {
            "reporting_period": readiness["latest_period"],
            "as_of_date": readiness["as_of_date"],
            "source_id": readiness["source_id"],
            "source_sha256": sha256_file(raw_path),
            "fund_count": readiness["fund_count"],
            "primary_gp_count": readiness["primary_gp_count"],
            "commitment_amount_krw_mn": readiness["commitment_amount_krw_mn"],
        }
        reporting_period = str(metadata["reporting_period"])
    source_sha256 = str(metadata["source_sha256"])

    page_bodies: list[tuple[str, str, str]] = []
    for page_path in public_page_paths(site_dir):
        path = site_dir / page_path
        if not path.is_file():
            raise GPReadModelError(f"Missing GP public page: {path}")
        page_html = path.read_text(encoding="utf-8")
        if "<!doctype html>" not in page_html.lower():
            raise GPReadModelError(f"GP public page is not complete HTML: {path}")
        if not _page_declares_reporting_period(page_html, reporting_period):
            raise GPReadModelError(f"GP public page does not show latest period {reporting_period}: {path}")
        page_bodies.append((page_path, page_html, _content_sha256(page_html)))

    snapshot_content_sha256 = _snapshot_content_sha256(
        [(page_path, content_sha256) for page_path, _, content_sha256 in page_bodies]
    )
    snapshot_id = (
        f"fss-{reporting_period.lower()}-"
        f"{source_sha256[:12]}-{snapshot_content_sha256[:12]}"
    )
    pages = [
        {
            "snapshot_id": snapshot_id,
            "page_path": page_path,
            "page_html": page_html,
            "content_sha256": content_sha256,
        }
        for page_path, page_html, content_sha256 in page_bodies
    ]

    snapshot = {
        "snapshot_id": snapshot_id,
        "reporting_period": metadata["reporting_period"],
        "as_of_date": metadata["as_of_date"],
        "source_id": metadata["source_id"],
        "source_sha256": source_sha256,
        "fund_count": metadata["fund_count"],
        "primary_gp_count": metadata["primary_gp_count"],
        "commitment_amount_krw_mn": metadata["commitment_amount_krw_mn"],
        "status": "staged",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"snapshot": snapshot, "pages": pages}


def apply_payload(payload: dict[str, object]) -> dict[str, object]:
    snapshot = payload.get("snapshot")
    pages = payload.get("pages")
    if not isinstance(snapshot, dict) or not isinstance(pages, list):
        raise GPReadModelError("Invalid GP public snapshot payload")
    snapshot_id = _clean_text(snapshot.get("snapshot_id"))
    if not snapshot_id:
        raise GPReadModelError("GP public snapshot id is missing")

    _rest_request(
        "gp_public_snapshots",
        method="POST",
        payload=snapshot,
        prefer="resolution=ignore-duplicates,return=minimal",
    )
    _rest_request(
        "gp_public_pages",
        method="POST",
        query={"on_conflict": "snapshot_id,page_path"},
        payload=pages,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    _rest_request(
        "rpc/publish_gp_public_snapshot",
        method="POST",
        payload={"target_snapshot_id": snapshot_id},
        prefer="return=minimal",
    )
    return {"snapshot_id": snapshot_id, "pages": len(pages), "status": "published"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish verified GP pages to the Supabase public read model")
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--expected-latest-period")
    parser.add_argument(
        "--canonical-manifest",
        type=Path,
        help="Use metadata restored from the current Supabase FSS snapshot instead of local raw Excel files.",
    )
    parser.add_argument("--payload-out", type=Path, default=DEFAULT_PAYLOAD_OUT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = prepare_payload(
            site_dir=args.site_dir,
            db_path=args.db,
            registry_path=args.registry,
            expected_latest_period=args.expected_latest_period or None,
            canonical_manifest=args.canonical_manifest,
        )
        args.payload_out.parent.mkdir(parents=True, exist_ok=True)
        args.payload_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        snapshot = payload["snapshot"]
        assert isinstance(snapshot, dict)
        print(f"payload_out={args.payload_out}")
        print(f"snapshot_id={snapshot['snapshot_id']}")
        print(f"reporting_period={snapshot['reporting_period']}")
        if args.apply:
            result = apply_payload(payload)
            print("supabase_gp_public_sync=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            print("supabase_gp_public_sync=skipped --apply not set")
    except (OSError, ValueError, GPReadModelError) as exc:
        print(f"FAIL GP public read-model sync: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
