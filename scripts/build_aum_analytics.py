#!/usr/bin/env python
"""Build AUM-style analytics from FSS PEF commitment data.

The FSS files provide commitment amounts, not NAV. These exports therefore use
commitment amount as the AUM-style proxy.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from build_gp_master_candidates import write_csv, write_xlsx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "db" / "private_equity.db"
DEFAULT_OUT = REPO_ROOT / "exports"


def fetch_dicts(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    cur = conn.execute(query, params)
    headers = [desc[0] for desc in cur.description]
    return [dict(zip(headers, row)) for row in cur.fetchall()]


def replace_table(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, object]]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    if not rows:
        return
    columns = list(rows[0].keys())
    column_defs = []
    for column in columns:
        if column.endswith("_count") or column in {"rank", "year", "active_in_latest_period"}:
            col_type = "INTEGER"
        elif column.endswith("_trn_krw") or column.endswith("_pct"):
            col_type = "REAL"
        else:
            col_type = "TEXT"
        column_defs.append(f"{column} {col_type}")
    conn.execute(f"CREATE TABLE {table_name} ({', '.join(column_defs)})")
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
        [[row.get(column, "") for column in columns] for row in rows],
    )


def split_names(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def build_full_credit_gp_period_aum(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = fetch_dicts(
        conn,
        """
        SELECT
            period_label,
            as_of_date,
            fund_id,
            canonical_gp_names,
            commitment_trn_krw,
            paid_in_trn_krw
        FROM fund_commitment_history
        WHERE canonical_gp_names IS NOT NULL
          AND TRIM(canonical_gp_names) <> ''
        """,
    )
    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        for gp_name in split_names(str(row["canonical_gp_names"])):
            key = (str(row["period_label"]), str(row["as_of_date"]), gp_name)
            if key not in grouped:
                grouped[key] = {
                    "period_label": row["period_label"],
                    "as_of_date": row["as_of_date"],
                    "gp_name": gp_name,
                    "active_fund_count": 0,
                    "commitment_aum_proxy_trn_krw": 0.0,
                    "paid_in_trn_krw": 0.0,
                }
            grouped[key]["active_fund_count"] = int(grouped[key]["active_fund_count"]) + 1
            grouped[key]["commitment_aum_proxy_trn_krw"] = round(
                float(grouped[key]["commitment_aum_proxy_trn_krw"]) + float(row["commitment_trn_krw"] or 0),
                6,
            )
            grouped[key]["paid_in_trn_krw"] = round(
                float(grouped[key]["paid_in_trn_krw"]) + float(row["paid_in_trn_krw"] or 0),
                6,
            )
    return sorted(
        grouped.values(),
        key=lambda row: (
            str(row["as_of_date"]),
            -float(row["commitment_aum_proxy_trn_krw"]),
            str(row["gp_name"]),
        ),
    )


def build_full_credit_ranking(full_credit_rows: list[dict[str, object]], ranking_period: str) -> list[dict[str, object]]:
    rows = [row for row in full_credit_rows if row["period_label"] == ranking_period]
    total = sum(float(row["commitment_aum_proxy_trn_krw"] or 0) for row in rows)
    ranked = sorted(rows, key=lambda row: (-float(row["commitment_aum_proxy_trn_krw"]), str(row["gp_name"])))
    output = []
    for rank, row in enumerate(ranked, start=1):
        commitment = float(row["commitment_aum_proxy_trn_krw"] or 0)
        output.append(
            {
                "rank": rank,
                "period_label": ranking_period,
                "gp_name": row["gp_name"],
                "active_fund_count": row["active_fund_count"],
                "commitment_aum_proxy_trn_krw": round(commitment, 6),
                "paid_in_trn_krw": row["paid_in_trn_krw"],
                "full_credit_share_pct": round(commitment / total * 100.0, 4) if total else "",
                "basis": "Full commitment amount credited to each listed GP/co-GP; totals can double-count co-managed funds.",
            }
        )
    return output


def build_cumulative_fund_attribution(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Assign each normalized fund once for the cumulative GP ranking.

    The public GP directory needs a stable, non-duplicative cumulative measure.
    A fund is therefore assigned to the first primary GP observed in the
    imported FSS history, while its largest disclosed commitment is counted
    once. Later GP observations are preserved as history, not an additional
    ranking credit.
    """
    return fetch_dicts(
        conn,
        """
        WITH primary_observation AS (
            SELECT
                fps.fund_id,
                fps.gp_id,
                gh.gp_name,
                rp.period_label,
                rp.as_of_date,
                fps.source_id,
                fps.sheet_name,
                fps.row_number,
                fps.row_hash,
                ROW_NUMBER() OVER (
                    PARTITION BY fps.fund_id
                    ORDER BY rp.as_of_date, rp.period_id, fps.snapshot_id
                ) AS first_primary_row,
                ROW_NUMBER() OVER (
                    PARTITION BY fps.fund_id
                    ORDER BY rp.as_of_date DESC, rp.period_id DESC, fps.snapshot_id DESC
                ) AS latest_primary_row
            FROM fund_period_snapshot fps
            JOIN reporting_period rp ON rp.period_id = fps.period_id
            JOIN gp_house gh ON gh.gp_id = fps.gp_id
            WHERE fps.gp_id IS NOT NULL
        ),
        first_primary AS (
            SELECT * FROM primary_observation WHERE first_primary_row = 1
        ),
        latest_primary AS (
            SELECT * FROM primary_observation WHERE latest_primary_row = 1
        ),
        primary_history AS (
            SELECT fund_id, COUNT(DISTINCT gp_id) AS observed_primary_gp_count
            FROM primary_observation
            GROUP BY fund_id
        ),
        max_commitment_observation AS (
            SELECT
                fps.fund_id,
                fps.source_id,
                fps.sheet_name,
                fps.row_number,
                fps.row_hash,
                fps.commitment_amount_krw_mn,
                ROW_NUMBER() OVER (
                    PARTITION BY fps.fund_id
                    ORDER BY fps.commitment_amount_krw_mn DESC, rp.as_of_date DESC, rp.period_id DESC, fps.snapshot_id DESC
                ) AS max_commitment_row
            FROM fund_period_snapshot fps
            JOIN reporting_period rp ON rp.period_id = fps.period_id
            WHERE fps.commitment_amount_krw_mn IS NOT NULL
        )
        SELECT
            fm.fund_id,
            fm.fund_name,
            first_primary.gp_id AS attributed_gp_id,
            first_primary.gp_name AS attributed_gp_name,
            first_primary.period_label AS attribution_period,
            first_primary.as_of_date AS attribution_as_of_date,
            first_primary.source_id AS attribution_source_id,
            first_primary.sheet_name AS attribution_sheet_name,
            first_primary.row_number AS attribution_row_number,
            first_primary.row_hash AS attribution_row_hash,
            max_commitment_observation.source_id AS max_commitment_source_id,
            max_commitment_observation.sheet_name AS max_commitment_sheet_name,
            max_commitment_observation.row_number AS max_commitment_row_number,
            max_commitment_observation.row_hash AS max_commitment_row_hash,
            ROUND(max_commitment_observation.commitment_amount_krw_mn / 1000000.0, 6) AS max_commitment_trn_krw,
            fm.active_in_latest_period,
            primary_history.observed_primary_gp_count,
            CASE WHEN primary_history.observed_primary_gp_count > 1 THEN 1 ELSE 0 END AS primary_gp_changed,
            latest_primary.gp_id AS latest_observed_gp_id,
            latest_primary.gp_name AS latest_observed_gp_name,
            latest_primary.period_label AS latest_observed_period,
            latest_primary.as_of_date AS latest_observed_as_of_date
        FROM fund_master fm
        JOIN first_primary ON first_primary.fund_id = fm.fund_id
        JOIN latest_primary ON latest_primary.fund_id = fm.fund_id
        JOIN primary_history ON primary_history.fund_id = fm.fund_id
        JOIN max_commitment_observation
          ON max_commitment_observation.fund_id = fm.fund_id
         AND max_commitment_observation.max_commitment_row = 1
        ORDER BY attributed_gp_name, fm.fund_name, fm.fund_id
        """,
    )


def build_cumulative_gp_ranking(attributions: list[dict[str, object]], period_label: str) -> list[dict[str, object]]:
    grouped: dict[tuple[int, str], dict[str, object]] = {}
    total = sum(float(row["max_commitment_trn_krw"] or 0) for row in attributions)
    for row in attributions:
        key = (int(row["attributed_gp_id"]), str(row["attributed_gp_name"]))
        item = grouped.setdefault(
            key,
            {
                "gp_id": key[0],
                "gp_name": key[1],
                "cumulative_fund_count": 0,
                "cumulative_commitment_proxy_trn_krw": 0.0,
                "active_fund_count_latest": 0,
            },
        )
        item["cumulative_fund_count"] = int(item["cumulative_fund_count"]) + 1
        item["cumulative_commitment_proxy_trn_krw"] = round(
            float(item["cumulative_commitment_proxy_trn_krw"]) + float(row["max_commitment_trn_krw"] or 0),
            6,
        )
        item["active_fund_count_latest"] = int(item["active_fund_count_latest"]) + int(
            row["active_in_latest_period"] or 0
        )

    ranking = sorted(
        grouped.values(),
        key=lambda row: (-float(row["cumulative_commitment_proxy_trn_krw"]), str(row["gp_name"])),
    )
    for rank, row in enumerate(ranking, start=1):
        amount = float(row["cumulative_commitment_proxy_trn_krw"])
        row.update(
            {
                "rank": rank,
                "as_of_period": period_label,
                "market_share_pct": round(amount / total * 100.0, 4) if total else 0.0,
                "basis": (
                    "Each normalized fund is credited once to its first observed FSS primary GP; "
                    "the fund's maximum disclosed total commitment is summed."
                ),
            }
        )
    return ranking


def build_cumulative_gp_change_history(attributions: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "fund_id": row["fund_id"],
            "fund_name": row["fund_name"],
            "rank_attributed_gp_id": row["attributed_gp_id"],
            "rank_attributed_gp_name": row["attributed_gp_name"],
            "attribution_period": row["attribution_period"],
            "latest_observed_gp_id": row["latest_observed_gp_id"],
            "latest_observed_gp_name": row["latest_observed_gp_name"],
            "latest_observed_period": row["latest_observed_period"],
            "observed_primary_gp_count": row["observed_primary_gp_count"],
            "max_commitment_trn_krw": row["max_commitment_trn_krw"],
            "ranking_treatment": "Retain the first observed primary GP allocation; do not double count later GP observations.",
        }
        for row in attributions
        if int(row["primary_gp_changed"] or 0) == 1
    ]


def validate_cumulative_analytics(
    conn: sqlite3.Connection,
    attributions: list[dict[str, object]],
    ranking: list[dict[str, object]],
) -> None:
    unique_fund_count, unique_fund_total = conn.execute(
        "SELECT COUNT(*), ROUND(SUM(max_commitment_trn_krw), 6) FROM fund_master"
    ).fetchone()
    attributed_total = round(sum(float(row["max_commitment_trn_krw"] or 0) for row in attributions), 6)
    ranked_total = round(
        sum(float(row["cumulative_commitment_proxy_trn_krw"] or 0) for row in ranking), 6
    )
    attributed_fund_ids = {int(row["fund_id"]) for row in attributions}
    if len(attributions) != len(attributed_fund_ids):
        raise RuntimeError("Cumulative attribution contains duplicate fund rows")
    if len(attributions) != int(unique_fund_count):
        raise RuntimeError(
            f"Cumulative attribution does not cover every normalized fund: {len(attributions)} != {unique_fund_count}"
        )
    if attributed_total != float(unique_fund_total) or ranked_total != float(unique_fund_total):
        raise RuntimeError(
            "Cumulative GP ranking does not reconcile to unique normalized funds: "
            f"fund_master={unique_fund_total}, attribution={attributed_total}, ranking={ranked_total}"
        )


def build(db_path: Path, out_dir: Path, ranking_period: str) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        gp_period_aum = fetch_dicts(
            conn,
            """
            SELECT
                rp.period_label,
                rp.as_of_date,
                gh.gp_id,
                gh.gp_name,
                COUNT(DISTINCT fps.fund_id) AS active_fund_count,
                ROUND(SUM(fps.commitment_amount_krw_mn) / 1000000.0, 6) AS commitment_aum_proxy_trn_krw,
                ROUND(SUM(fps.paid_in_amount_krw_mn) / 1000000.0, 6) AS paid_in_trn_krw
            FROM fund_period_snapshot fps
            JOIN reporting_period rp ON rp.period_id = fps.period_id
            JOIN gp_house gh ON gh.gp_id = fps.gp_id
            GROUP BY rp.period_id, gh.gp_id
            ORDER BY rp.as_of_date, commitment_aum_proxy_trn_krw DESC, gh.gp_name
            """,
        )

        gp_ranking = fetch_dicts(
            conn,
            """
            WITH gp_amount AS (
                SELECT
                    gh.gp_id,
                    gh.gp_name,
                    COUNT(DISTINCT fps.fund_id) AS active_fund_count,
                    SUM(fps.commitment_amount_krw_mn) AS commitment_amount_krw_mn,
                    SUM(fps.paid_in_amount_krw_mn) AS paid_in_amount_krw_mn
                FROM fund_period_snapshot fps
                JOIN reporting_period rp ON rp.period_id = fps.period_id
                JOIN gp_house gh ON gh.gp_id = fps.gp_id
                WHERE rp.period_label = ?
                GROUP BY gh.gp_id
            ),
            total_amount AS (
                SELECT SUM(commitment_amount_krw_mn) AS total_commitment
                FROM gp_amount
            )
            SELECT
                ROW_NUMBER() OVER (ORDER BY gp_amount.commitment_amount_krw_mn DESC, gp_amount.gp_name) AS rank,
                ? AS period_label,
                gp_amount.gp_id,
                gp_amount.gp_name,
                gp_amount.active_fund_count,
                ROUND(gp_amount.commitment_amount_krw_mn / 1000000.0, 6) AS commitment_aum_proxy_trn_krw,
                ROUND(gp_amount.paid_in_amount_krw_mn / 1000000.0, 6) AS paid_in_trn_krw,
                ROUND(gp_amount.commitment_amount_krw_mn / total_amount.total_commitment * 100.0, 4) AS market_share_pct
            FROM gp_amount
            CROSS JOIN total_amount
            ORDER BY rank
            """,
            (ranking_period, ranking_period),
        )

        new_funds_by_year = fetch_dicts(
            conn,
            """
            SELECT
                CAST(SUBSTR(established_date, 1, 4) AS INTEGER) AS year,
                COUNT(*) AS new_fund_count,
                ROUND(SUM(first_commitment_trn_krw), 6) AS first_seen_commitment_trn_krw,
                ROUND(SUM(latest_commitment_trn_krw), 6) AS latest_commitment_trn_krw,
                ROUND(SUM(max_commitment_trn_krw), 6) AS max_commitment_trn_krw,
                SUM(CASE WHEN active_in_latest_period = 1 THEN 1 ELSE 0 END) AS active_in_latest_count
            FROM fund_master
            WHERE established_date GLOB '[0-9][0-9][0-9][0-9]-*'
            GROUP BY CAST(SUBSTR(established_date, 1, 4) AS INTEGER)
            ORDER BY year
            """,
        )

        new_funds_by_gp_year = fetch_dicts(
            conn,
            """
            WITH first_gp AS (
                SELECT fund_id, canonical_gp_names
                FROM (
                    SELECT
                        fund_id,
                        canonical_gp_names,
                        ROW_NUMBER() OVER (PARTITION BY fund_id ORDER BY first_as_of_date) AS rn
                    FROM fund_gp_history
                )
                WHERE rn = 1
            )
            SELECT
                CAST(SUBSTR(fm.established_date, 1, 4) AS INTEGER) AS year,
                first_gp.canonical_gp_names AS gp_names_at_first_seen,
                COUNT(*) AS new_fund_count,
                ROUND(SUM(fm.first_commitment_trn_krw), 6) AS first_seen_commitment_trn_krw,
                ROUND(SUM(fm.latest_commitment_trn_krw), 6) AS latest_commitment_trn_krw,
                ROUND(SUM(fm.max_commitment_trn_krw), 6) AS max_commitment_trn_krw
            FROM fund_master fm
            LEFT JOIN first_gp ON first_gp.fund_id = fm.fund_id
            WHERE fm.established_date GLOB '[0-9][0-9][0-9][0-9]-*'
            GROUP BY year, first_gp.canonical_gp_names
            ORDER BY year, first_seen_commitment_trn_krw DESC, gp_names_at_first_seen
            """,
        )

        new_funds_2024 = fetch_dicts(
            conn,
            """
            SELECT
                fm.fund_id,
                fm.fund_name,
                fm.established_date,
                fm.latest_canonical_gp_names,
                fm.raw_gp_name_variants,
                fm.first_seen_period,
                fm.last_seen_period,
                fm.active_in_latest_period,
                fm.first_commitment_trn_krw,
                fm.latest_commitment_trn_krw,
                fm.max_commitment_trn_krw,
                fm.lifecycle_status,
                fm.latest_source_url
            FROM fund_master fm
            WHERE fm.established_date >= '2024-01-01'
              AND fm.established_date < '2025-01-01'
            ORDER BY fm.established_date, fm.fund_name
            """,
        )

        new_funds_by_quarter = fetch_dicts(
            conn,
            """
            SELECT
                SUBSTR(established_date, 1, 4) || 'Q' ||
                    ((CAST(SUBSTR(established_date, 6, 2) AS INTEGER) - 1) / 3 + 1) AS established_quarter,
                COUNT(*) AS new_fund_count,
                ROUND(SUM(first_commitment_trn_krw), 6) AS first_seen_commitment_trn_krw,
                ROUND(SUM(latest_commitment_trn_krw), 6) AS latest_commitment_trn_krw,
                ROUND(SUM(max_commitment_trn_krw), 6) AS max_commitment_trn_krw
            FROM fund_master
            WHERE established_date GLOB '[0-9][0-9][0-9][0-9]-*'
            GROUP BY established_quarter
            ORDER BY established_quarter
            """,
        )
        gp_period_aum_full_credit = build_full_credit_gp_period_aum(conn)
        gp_ranking_full_credit = build_full_credit_ranking(gp_period_aum_full_credit, ranking_period)
        cumulative_fund_attribution = build_cumulative_fund_attribution(conn)
        cumulative_gp_ranking = build_cumulative_gp_ranking(cumulative_fund_attribution, ranking_period)
        cumulative_gp_changes = build_cumulative_gp_change_history(cumulative_fund_attribution)
        validate_cumulative_analytics(conn, cumulative_fund_attribution, cumulative_gp_ranking)

        out_dir.mkdir(parents=True, exist_ok=True)
        exports = [
            ("analytics_gp_period_aum", gp_period_aum),
            (f"analytics_gp_ranking_{ranking_period}", gp_ranking),
            ("analytics_gp_period_aum_full_credit", gp_period_aum_full_credit),
            (f"analytics_gp_ranking_{ranking_period}_full_credit", gp_ranking_full_credit),
            ("analytics_gp_cumulative_fund_attribution", cumulative_fund_attribution),
            ("analytics_gp_cumulative_ranking", cumulative_gp_ranking),
            ("analytics_gp_cumulative_change_history", cumulative_gp_changes),
            ("analytics_new_funds_by_year", new_funds_by_year),
            ("analytics_new_funds_by_gp_year", new_funds_by_gp_year),
            ("analytics_new_funds_by_quarter", new_funds_by_quarter),
            ("analytics_new_funds_2024", new_funds_2024),
        ]
        for filename, rows in exports:
            write_csv(out_dir / f"{filename}.csv", rows)
            replace_table(conn, filename, rows)

        write_xlsx(
            out_dir / "aum_analytics.xlsx",
            [
                ("gp_period_aum", gp_period_aum),
                (f"gp_rank_{ranking_period}", gp_ranking),
                ("gp_aum_full_credit", gp_period_aum_full_credit),
                (f"gp_rank_{ranking_period}_fc", gp_ranking_full_credit),
                ("gp_cumulative_attribution", cumulative_fund_attribution),
                ("gp_cumulative_rank", cumulative_gp_ranking),
                ("gp_cumulative_changes", cumulative_gp_changes),
                ("new_by_year", new_funds_by_year),
                ("new_by_gp_year", new_funds_by_gp_year),
                ("new_by_quarter", new_funds_by_quarter),
                ("new_funds_2024", new_funds_2024),
            ],
        )
        conn.commit()

        return {name: len(rows) for name, rows in exports}
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AUM-style analytics exports")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--ranking-period", default="2024Q4")
    args = parser.parse_args()

    counts = build(args.db, args.out, args.ranking_period)
    for key, value in counts.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
