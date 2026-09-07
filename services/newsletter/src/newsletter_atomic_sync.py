"""Upload bounded private parts, then commit a newsletter model in one RPC.

Uploading or retrying a part never changes canonical/public rows. Only the
database RPC can publish a complete, validated set, in a single transaction.
"""

from __future__ import annotations

import json
from typing import Any, Callable
from uuid import uuid4

MAX_PART_BYTES = 750_000
MAX_PART_ROWS = 250


def publish_atomic(
    payload: dict[str, list[dict[str, Any]]],
    *,
    model: str,
    request: Callable[..., Any],
) -> dict[str, int]:
    if model not in {"canonical", "public"}:
        raise ValueError(f"Unknown newsletter model: {model}")
    for table, rows in payload.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"Invalid newsletter rows for {table}")
    sync_id = str(uuid4())
    counts = {table: len(rows) for table, rows in payload.items()}
    for table, rows in payload.items():
        part: list[dict[str, Any]] = []
        size = 2
        part_no = 0

        def upload() -> None:
            request(
                "newsletter_sync_parts",
                method="POST",
                query={"on_conflict": "sync_id,table_name,part_no"},
                payload=[{
                    "sync_id": sync_id, "model": model, "table_name": table,
                    "part_no": part_no, "rows": part,
                }],
                prefer="resolution=merge-duplicates,return=minimal",
            )

        for row in rows:
            row_bytes = len(json.dumps(row, ensure_ascii=False).encode("utf-8")) + 1
            if part and (len(part) >= MAX_PART_ROWS or size + row_bytes > MAX_PART_BYTES):
                upload()
                part_no += 1
                part = []
                size = 2
            part.append(row)
            size += row_bytes
        if part:
            upload()
    # The RPC records a receipt in the same transaction. Its HTTP retry can
    # return that receipt even after the committed staging rows were removed.
    result = request(
        "rpc/publish_newsletter_sync",
        method="POST",
        payload={"target_sync_id": sync_id, "target_model": model, "expected_counts": counts},
    )
    if result != counts:
        raise RuntimeError("Newsletter atomic sync did not return the expected committed counts")
    return counts
