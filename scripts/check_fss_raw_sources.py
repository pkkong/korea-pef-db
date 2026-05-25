#!/usr/bin/env python3
"""Validate local FSS PEF raw source files against the source registry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "data" / "source_registry_fss_pef.csv"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "fss_pef"
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"


@dataclass(frozen=True)
class RegistryEntry:
    row_number: int
    source_id: str
    local_file_text: str
    local_file: Path


@dataclass(frozen=True)
class DbSource:
    sha256: str
    local_path: str


def display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def normalize_registry_path(value: str, registry_path: Path) -> Path:
    path = Path(value.strip().replace("\\", "/"))
    if path.is_absolute():
        return path
    if registry_path.resolve(strict=False) != DEFAULT_REGISTRY.resolve(strict=False):
        return registry_path.parent / path
    return REPO_ROOT / path


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_registry(path: Path) -> tuple[list[RegistryEntry], list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"registry not found: {display_path(path)}")

    entries: list[RegistryEntry] = []
    warnings: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = set(reader.fieldnames or [])
        missing_fields = {"source_id", "local_file"} - fieldnames
        if missing_fields:
            fields = ", ".join(sorted(missing_fields))
            raise ValueError(f"registry missing required column(s): {fields}")

        for row_number, row in enumerate(reader, start=2):
            source_id = (row.get("source_id") or "").strip()
            local_file_text = (row.get("local_file") or "").strip()
            if not source_id:
                warnings.append(f"row {row_number}: missing source_id; skipped")
                continue
            if not local_file_text:
                warnings.append(f"{source_id}: missing local_file in registry")
                entries.append(RegistryEntry(row_number, source_id, local_file_text, REPO_ROOT))
                continue
            entries.append(
                RegistryEntry(
                    row_number=row_number,
                    source_id=source_id,
                    local_file_text=local_file_text,
                    local_file=normalize_registry_path(local_file_text, path),
                )
            )
    return entries, warnings


def load_db_sources(db_path: Path) -> tuple[dict[str, DbSource] | None, list[str]]:
    warnings: list[str] = []
    if not db_path.exists():
        warnings.append(f"DB not found; skipping source_document sha comparison: {display_path(db_path)}")
        return None, warnings

    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        warnings.append(f"could not open DB; skipping source_document sha comparison: {exc}")
        return None, warnings

    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_document'"
        ).fetchone()
        if not table_exists:
            warnings.append("DB table source_document not found; skipping sha comparison")
            return None, warnings

        columns = {row[1] for row in conn.execute("PRAGMA table_info(source_document)").fetchall()}
        missing_columns = {"source_id", "sha256"} - columns
        if missing_columns:
            fields = ", ".join(sorted(missing_columns))
            warnings.append(f"DB source_document missing expected column(s) {fields}; skipping sha comparison")
            return None, warnings

        local_path_expr = "local_path" if "local_path" in columns else "''"
        rows = conn.execute(f"SELECT source_id, sha256, {local_path_expr} FROM source_document").fetchall()
        return {
            str(source_id): DbSource(sha256=str(sha256 or "").strip(), local_path=str(local_path or "").strip())
            for source_id, sha256, local_path in rows
            if source_id
        }, warnings
    except sqlite3.Error as exc:
        warnings.append(f"DB source_document read failed; skipping sha comparison: {exc}")
        return None, warnings
    finally:
        conn.close()


def format_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def check_entries(
    entries: list[RegistryEntry],
    raw_dir: Path,
    db_sources: dict[str, DbSource] | None,
) -> tuple[int, int, int, int]:
    errors = 0
    warnings = 0
    checked = 0
    db_compared = 0

    for entry in entries:
        path = entry.local_file
        label = f"{entry.source_id} {entry.local_file_text or '<missing local_file>'}"

        if not entry.local_file_text:
            print(f"ERROR {label}: registry local_file is blank")
            errors += 1
            continue

        if not is_under(path, raw_dir):
            print(f"ERROR {label}: local_file is outside {display_path(raw_dir)}")
            errors += 1
            continue

        if not path.exists():
            print(f"ERROR {label}: raw file missing")
            errors += 1
            continue

        if not path.is_file():
            print(f"ERROR {label}: path exists but is not a file")
            errors += 1
            continue

        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            print(f"ERROR {label}: raw file is empty")
            errors += 1
            continue

        file_sha = sha256_file(path)
        checked += 1

        db_status = "db=skipped"
        if db_sources is not None:
            db_source = db_sources.get(entry.source_id)
            if db_source is None:
                print(f"WARNING {entry.source_id}: no source_document row in DB; sha comparison skipped")
                warnings += 1
                db_status = "db=missing-row"
            elif not db_source.sha256:
                print(f"WARNING {entry.source_id}: DB source_document.sha256 is blank; sha comparison skipped")
                warnings += 1
                db_status = "db=blank-sha"
            elif db_source.sha256.lower() != file_sha.lower():
                print(
                    f"ERROR {label}: sha256 mismatch "
                    f"file={file_sha} db={db_source.sha256}"
                )
                errors += 1
                db_status = "db=sha-mismatch"
            else:
                db_compared += 1
                db_status = "db=sha-ok"

        if db_status != "db=sha-mismatch":
            print(
                f"OK {entry.source_id}: size={format_size(size_bytes)} "
                f"sha256={file_sha} {db_status}"
            )

    return errors, warnings, checked, db_compared


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check FSS PEF raw source reproducibility")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="FSS source registry CSV")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="Expected raw source directory")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite DB for optional sha comparison")
    parser.add_argument("--no-db-check", action="store_true", help="Skip DB source_document sha comparison")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry_path = args.registry if args.registry.is_absolute() else REPO_ROOT / args.registry
    raw_dir = args.raw_dir if args.raw_dir.is_absolute() else REPO_ROOT / args.raw_dir
    db_path = args.db if args.db.is_absolute() else REPO_ROOT / args.db

    print("FSS raw source health check")
    print(f"registry={display_path(registry_path)}")
    print(f"raw_dir={display_path(raw_dir)}")

    try:
        entries, warnings = read_registry(registry_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 2

    for warning in warnings:
        print(f"WARNING {warning}")

    db_sources: dict[str, DbSource] | None = None
    db_warnings: list[str] = []
    if args.no_db_check:
        db_warnings.append("DB check disabled by --no-db-check")
    else:
        print(f"db={display_path(db_path)}")
        db_sources, db_warnings = load_db_sources(db_path)
    for warning in db_warnings:
        print(f"WARNING {warning}")

    errors, entry_warnings, checked, db_compared = check_entries(entries, raw_dir, db_sources)
    warning_count = len(warnings) + len(db_warnings) + entry_warnings

    print(
        "SUMMARY "
        f"registry_rows={len(entries)} "
        f"files_checked={checked} "
        f"db_sha_compared={db_compared} "
        f"warnings={warning_count} "
        f"errors={errors}"
    )
    if errors:
        print("FAIL FSS raw source health check failed")
        return 1
    print("PASS FSS raw source health check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
