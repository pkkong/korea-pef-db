# FSS PEF Quarterly Status Ingestion Plan

## Goal

Build the first normalized layer for Korea private equity data using FSS quarterly status files:

- `경영참여형 사모집합투자기구(PEF) 현황`
- `기관전용 사모집합투자기구 현황`

The output should support these questions:

- Which GP was active in each quarter?
- Which funds existed in each quarter?
- Which funds were first seen, newly established, liquidated, or disappeared from the active list?
- What was each fund's commitment amount and paid-in amount by quarter?
- What was each GP's aggregate commitment amount by quarter?

## Source Handling

Store every downloaded FSS file as immutable raw evidence under:

```text
data/raw/fss_pef/
```

Track each source in:

```text
data/source_registry_fss_pef.csv
```

Required registry fields:

- `source_id`: stable ID, e.g. `FSS_PEF_2024_Q4`
- `as_of_date`: quarter-end date, e.g. `2024-12-31`
- `period_label`: e.g. `2024Q4`
- `regime`: `management_participation` or `institutional`
- `title`: FSS post title
- `source_url`: original FSS URL when available
- `post_url`: FSS board post URL
- `download_url`: FSS attachment download URL
- `posted_date`: FSS board post date
- `original_file_name`: original attachment filename
- `local_file`: saved raw file path
- `notes`: source notes

## Normalized Tables

The schema in `schema/fss_pef.sql` creates:

- `source_document`: evidence file metadata
- `reporting_period`: quarter metadata
- `gp_house`: GP/house master
- `pef_fund`: fund master
- `fund_gp_affiliation`: fund-GP relationship
- `source_row`: raw parsed rows
- `fund_period_snapshot`: fund-by-quarter facts
- `fund_event`: inferred or explicit events

This keeps FSS data compatible with later people, deal, LP, and portfolio-company tables.

## Event Policy

Event types should be conservative:

- `first_seen`: first quarter where the fund appears in the imported series
- `established`: explicit establishment/new-fund row or establishment date from the file
- `liquidated`: explicit liquidation/termination row or liquidation date from the file
- `absent_after_seen`: optional later inference only when a continuous quarterly series exists

Do not infer liquidation from absence unless every intervening quarter is loaded.

## Amount Policy

FSS PEF status files commonly use `억원`, but the parser stores both:

- raw text amount as disclosed
- normalized `KRW million` amount where a unit can be detected or provided

Default parser unit is `억원`, so `10,000` becomes `1,000,000` KRW million.

## First Build Order

1. 새 분기 확인 시에만 `python scripts/fetch_fss_pef_sources.py`를 실행해 discoverable FSS common-board attachments를 수집한다. 새 Excel과 `data/source_registry_fss_pef.csv`를 SHA 검증 후 GitHub에 commit한다. 정기 GP 배포 workflow는 이 명령을 실행하지 않고 versioned 원본을 사용한다.
2. Download older legacy FSS files that are no longer exposed by the new board if needed.
3. Run workbook inspection to verify sheet and header layouts.
4. Import each workbook into SQLite.
5. Review GP aggregate rankings against articles or FSS annual statistics.
6. Backfill all available quarters.

## Current Coverage

As of the 2026-08-21 ingestion pass, the FSS common-board search exposes:

- `2015-10-31` through `2021-09-30` legacy `경영참여형` PEF status files
- `2022Q1` through `2023Q4` institutional PEF status files
- `2024Q4`
- `2025Q4` (`2025-12-31` 기준, 2026-07-02 게시)

Older legacy files were found by searching the FSS board with the broader keyword `경영참여` and walking `pageIndex`.

Note that the 2015-2017 legacy files are often as of January, April, July, and October month-end rather than calendar quarter-end. The pipeline stores the exact `as_of_date` and derives a quarter-style `period_label` only for grouping.

The current registry contains 34 immutable raw source files. The 2015Q4 and
2016Q1 legacy `.xls` files are retained as raw evidence but are not imported by
the standard-library `.xlsx` parser. The reproducible normalized dataset starts
at 2016Q2 and contains 32 source documents and 24,624 fund-period snapshots.

Before publishing FSS statistics, run:

```bash
python3 scripts/check_fss_raw_sources.py
python3 scripts/check_fss_statistics_ready.py --expected-latest-period 2025Q4
```

The second check requires the latest raw file, matching DB SHA-256, latest
reporting period, non-zero market totals, and a complete primary-GP ranking.
It also fails when the latest FSS as-of date is more than 400 days old.
