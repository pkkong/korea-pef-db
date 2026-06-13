# Entity Data Model

## Purpose

This document translates the service structure into a practical data model.
It is the working data dictionary for Korea PEF Intelligence. The operating
contract between raw data, canonical entities, public views, and static HTML is
maintained in `docs/data_operating_model.md`.

The rule is simple:

- Each entity needs a stable ID.
- Each important fact needs a source or confidence state.
- Each future crawler or manual import should land in these structures, not in
  one-off spreadsheets.

## Current Database Baseline

Current SQLite DB:

- `db/private_equity.db`

Core schemas already present:

- `schema/fss_pef.sql`
- `services/newsletter/schema/daily_news.sql`

Current production-like entities:

- GP: `gp_house`, `gp_profile`, `gp_identifier`, `gp_profile_source`
- Fund: `pef_fund`, `fund_master`, `fund_period_snapshot`,
  `fund_commitment_history`, `fund_event`, `fund_gp_affiliation`
- Period/source: `reporting_period`, `source_document`, `source_row`
- News: `news_source`, `news_run`, `news_document`, `news_tag`,
  `news_entity_link`
- People foundation: `person`, `person_alias`, `person_role`,
  `person_education`, `person_source`, `person_news_link`
- Analytics: `analytics_gp_period_aum`, `analytics_gp_period_aum_full_credit`,
  `analytics_gp_ranking_2024Q4`, `analytics_new_funds_by_year`,
  `analytics_new_funds_by_quarter`

## Core Modeling Rules

### Stable IDs

- Internal IDs should be numeric or deterministic text IDs.
- Display names can change; IDs should not.
- Raw names from source documents must be preserved.
- Canonical names should be produced through explicit mapping or review rules.

### Source Evidence

Every non-FSS profile fact should be traceable to evidence.

Evidence fields should include:

- `source_url`
- `source_title`
- `source_type`
- `source_grade`
- `evidence_scope`
- `evidence_value`
- `verification_status`
- `captured_at`
- `notes`

Current implementation:

- GP evidence exists in `gp_profile_source`.
- FSS source rows exist in `source_row`.
- News source facts exist in `news_document` and `news_entity_link`.

### Confidence Status

Recommended common confidence labels:

- `verified`: official or authoritative source confirmed.
- `source_derived`: directly derived from source but not independently reviewed.
- `review_needed`: useful candidate but needs human review.
- `conflict`: sources disagree.
- `unknown`: blank or unavailable.

Do not fill unknown fields by guessing.

## Entity: GP

### User-Facing Meaning

A GP is a private equity house or manager that appears in FSS PEF data or is
otherwise relevant to Korean institutional PEF.

### Current Tables

- `gp_house`
- `gp_house_alias`
- `gp_alias_merge_rule`
- `gp_master_candidate`
- `gp_profile`
- `gp_identifier`
- `gp_profile_source`
- `gp_profile_research_worklist`

### Primary Key

- Current source key: `gp_house.gp_id`
- Profile key: `gp_profile.gp_profile_id`
- Business-facing key: `gp_profile.source_gp_id` linked to `gp_house.gp_id`

### Required Fields

- `standard_gp_name`
- `gp_name_norm`
- `profile_status`
- `verification_level`
- `first_seen_period`
- `last_seen_period`
- `active_in_latest_period`

### Important Optional Fields

- `display_name_ko`
- `legal_entity_name_ko`
- `legal_entity_name_en`
- `homepage_url`
- `established_date`
- `firm_founded_date`
- `firm_founded_year`
- `representative_name`
- `headquarters_address`
- `phone_number`
- `contact_email`
- `business_registration_number`
- `corporate_registration_number`
- `financial_registration_number`
- `license_type`
- `license_status`
- `company_category`
- `firm_description`

### Existing Derived Metrics

- `latest_primary_rank`
- `latest_primary_active_fund_count`
- `latest_primary_aum_proxy_krw_100mn`
- `latest_primary_market_share_pct`
- `cumulative_primary_rank`
- `cumulative_primary_fund_count`
- `cumulative_primary_commitment_proxy_krw_100mn`

### Relationships

- GP to Fund: `fund_gp_affiliation`, `fund_period_snapshot.gp_id`,
  `fund_master.latest_canonical_gp_names`
- GP to News: `news_entity_link.entity_type = 'GP'`
- GP to Source Evidence: `gp_profile_source`
- GP to Identifier: `gp_identifier`

### Gaps

- GP to Person relationship is not built.
- GP to Deal relationship is not built.
- GP to Report relationship should reuse `news_document` short term or get a
  separate `report_document` table later.

## Entity: Fund

### User-Facing Meaning

A PEF fund disclosed in FSS quarterly status files.

### Current Tables

- `pef_fund`
- `fund_master`
- `fund_period_snapshot`
- `fund_commitment_history`
- `fund_gp_affiliation`
- `fund_event`
- `fund_lifecycle_event`

### Primary Key

- `fund_id`

### Required Fields

- `fund_name`
- `fund_name_norm`
- `first_seen_period`
- `last_seen_period`
- `active_in_latest_period`
- `lifecycle_status`

### Important Optional Fields

- `fund_type_master`
- `established_date`
- `liquidation_date`
- `latest_canonical_gp_names`
- `all_canonical_gp_names`
- `raw_gp_name_variants`
- `first_commitment_trn_krw`
- `latest_commitment_trn_krw`
- `max_commitment_trn_krw`
- `latest_paid_in_trn_krw`
- `latest_source_url`

### Period Snapshot Fields

- `period_id`
- `source_id`
- `fund_name_raw`
- `gp_name_raw`
- `fund_type_raw`
- `status_raw`
- `established_date_raw`
- `liquidation_date_raw`
- `commitment_amount_raw`
- `commitment_amount_krw_mn`
- `paid_in_amount_raw`
- `paid_in_amount_krw_mn`
- `raw_row_json`
- `row_hash`

### Relationships

- Fund to GP: `fund_gp_affiliation`, `fund_period_snapshot.gp_id`
- Fund to Source: `fund_period_snapshot.source_id`, `source_row`
- Fund to Period: `fund_period_snapshot.period_id`
- Fund to News: future `news_entity_link.entity_type = 'Fund'`
- Fund to Deal: future deal-fund link table

### Gaps

- Needs validation flags for same-name ambiguity, GP change, amount jump,
  disappearance, reappearance, and raw-source conflict.
- Needs source-backed review notes for fund merges/splits.

## Entity: Reporting Period

### User-Facing Meaning

The quarter or month-end point in time represented by an FSS PEF disclosure.

### Current Tables

- `reporting_period`
- `source_document`

### Required Fields

- `period_id`
- `period_label`
- `as_of_date`
- `year`
- `quarter`
- `regime`

### Relationships

- Reporting Period to Fund Snapshot.
- Reporting Period to GP AUM Analytics.
- Reporting Period to Source Document.

### Gaps

- None critical. Keep source document registry clean.

## Entity: Source Document

### User-Facing Meaning

An official source file, news article, report, or web page that supports a data
point.

### Current Tables

- FSS: `source_document`, `source_row`
- News/articles: `news_document`
- GP profile evidence: `gp_profile_source`

### Required Fields

- `source_id` or `news_id`
- `title`
- `publisher`
- `document_type`
- `source_url`
- `local_path` when downloaded
- `sha256` or `content_hash` when available
- `fetched_at`

### Relationships

- Source Document to Fund Snapshot.
- Source Document to GP Profile Evidence.
- News Document to News Entity Link.
- Future Report Document to GP/Deal/LP.

### Gap

There is no unified `evidence` table across all entity types yet.
Short term, keep current evidence tables. Long term, create a generic
`entity_evidence` table.

## Entity: News

### User-Facing Meaning

Articles and public posts used for daily clipping, GP update worklists, and
future deal/person/report discovery.

### Current Tables

- `news_source`
- `news_run`
- `news_document`
- `news_tag`
- `news_entity_link`

### Primary Key

- `news_id`

### Required Fields

- `source_code`
- `source_url`
- `normalized_source_url`
- `publisher`
- `title`
- `published_at`
- `discovered_at`
- `document_type`
- `relevance_score`
- `review_status`
- `is_pe_relevant`

### Relationships

- News to GP: current `news_entity_link.entity_type = 'GP'`
- News to Fund: future `entity_type = 'Fund'`
- News to Deal: future `entity_type = 'Deal'`
- News to Person: future `entity_type = 'Person'`
- News to LP: future `entity_type = 'LP'`
- News to Adviser: future `entity_type = 'Adviser'`

### Gaps

- Needs stronger review state for daily/weekly publishing.
- Needs report-library treatment for non-news PDF/report materials.
- Needs deal-candidate extraction.

## Entity: Person

### User-Facing Meaning

Professionals connected to GP houses, deals, LPs, advisers, or regulators.

### Current Tables

- `person`
- `person_alias`
- `person_role`
- `person_education`
- `person_source`
- `person_news_link`
- `v_person_current_gp`
- `v_person_profile_summary`

Schema file:

- `schema/people.sql`

Input files:

- `data/people_input.csv`
- `data/person_role_input.csv`
- `data/person_education_input.csv`

Import script:

- `scripts/import_people_csv.py`

### Required Fields

- `person_name_ko`
- `person_name_norm`
- `profile_status`
- `verification_level`
- at least one source row before public display

### Sensitive / High-Risk Fields

- Birth year.
- Age cohort.
- School class year.
- Personal social media URLs.

Rule:

- Only fill these when source-backed.
- Do not infer from education or career sequence.

### Relationships

- Person to GP: `person_role.org_type = 'GP'`
- Person to Deal: future `deal_person_role`
- Person to News: `news_entity_link.entity_type = 'Person'`

### Current Status

- People DB schema exists in SQLite.
- CSV import and export paths exist.
- Premier Partners and MBK Partners teams are loaded from official team pages.
- Dashboard JSON and public GP detail page include People summary, career, and education data.

## Entity: Deal

### User-Facing Meaning

An investment, acquisition, sale, exit, recapitalization, or other transaction
connected to GP/fund activity.

### Current Direction

LP Notice must move from row/event thinking to business lifecycle thinking.
`lp_commitment_notice` currently behaves like an event table. Public screens
should read a lifecycle public view that groups one commitment business into one
card. A future canonical `lp_commitment_program` layer should make that grouping
explicit.

### Proposed Tables

```sql
deal (
    deal_id INTEGER PRIMARY KEY,
    deal_title TEXT NOT NULL,
    target_company_id INTEGER,
    target_company_name TEXT NOT NULL,
    deal_type TEXT,
    announced_date TEXT,
    closed_date TEXT,
    deal_status TEXT,
    sector TEXT,
    deal_amount_krw_mn REAL,
    enterprise_value_krw_mn REAL,
    stake_pct REAL,
    summary TEXT,
    confidence_status TEXT NOT NULL,
    primary_source_url TEXT,
    created_at TEXT,
    updated_at TEXT
)
```

```sql
deal_party (
    deal_party_id INTEGER PRIMARY KEY,
    deal_id INTEGER NOT NULL,
    party_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    entity_name TEXT NOT NULL,
    role_detail TEXT,
    source_url TEXT,
    verification_status TEXT
)
```

```sql
deal_fund_link (
    deal_id INTEGER NOT NULL,
    fund_id INTEGER NOT NULL,
    link_confidence TEXT NOT NULL,
    source_url TEXT,
    notes TEXT,
    PRIMARY KEY (deal_id, fund_id)
)
```

```sql
deal_adviser (
    deal_adviser_id INTEGER PRIMARY KEY,
    deal_id INTEGER NOT NULL,
    adviser_type TEXT NOT NULL,
    adviser_name TEXT NOT NULL,
    adviser_entity_id TEXT,
    side TEXT,
    source_url TEXT,
    verification_status TEXT
)
```

### Required Fields

- `deal_title`
- `target_company_name`
- `deal_type`
- `confidence_status`
- `primary_source_url`

### Relationships

- Deal to GP: `deal_party.entity_type = 'GP'`
- Deal to Fund: `deal_fund_link`
- Deal to Company: `target_company_id`
- Deal to Adviser: `deal_adviser`
- Deal to Person: future `deal_person_role`
- Deal to News: `news_entity_link.entity_type = 'Deal'`

### Gaps

- No deal schema exists yet.
- Start from news-derived candidates, not manual free text.

## Entity: Company

### User-Facing Meaning

A target company, portfolio company, adviser, LP, or other organization that is
not necessarily a GP.

### Proposed Tables

```sql
organization (
    org_id INTEGER PRIMARY KEY,
    org_name_ko TEXT NOT NULL,
    org_name_en TEXT,
    org_name_norm TEXT NOT NULL,
    org_type TEXT NOT NULL,
    business_registration_number TEXT,
    corporate_registration_number TEXT,
    homepage_url TEXT,
    headquarters_address TEXT,
    profile_status TEXT NOT NULL,
    verification_level TEXT NOT NULL,
    primary_source_url TEXT,
    created_at TEXT,
    updated_at TEXT
)
```

### Organization Types

- `PortfolioCompany`
- `Adviser`
- `LP`
- `LawFirm`
- `AccountingFirm`
- `Lender`
- `Regulator`
- `Media`

### Relationships

- Organization to Deal.
- Organization to Person.
- Organization to News.
- Organization to LP program when `org_type = 'LP'`.

### Gaps

- Not built.
- Needed before Deal DB scales.

## Entity: LP / Commitment Program

### User-Facing Meaning

LPs and their public private-equity commitment programs, RFPs, and GP selection
results.

### Proposed Tables

```sql
lp_program (
    program_id INTEGER PRIMARY KEY,
    lp_org_id INTEGER NOT NULL,
    program_title TEXT NOT NULL,
    strategy TEXT,
    commitment_amount_krw_mn REAL,
    announcement_date TEXT,
    application_deadline TEXT,
    selection_date TEXT,
    status TEXT,
    primary_source_url TEXT,
    confidence_status TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
)
```

```sql
lp_program_selection (
    selection_id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL,
    selected_gp_id INTEGER,
    selected_gp_name TEXT NOT NULL,
    selected_amount_krw_mn REAL,
    source_url TEXT,
    verification_status TEXT,
    notes TEXT
)
```

### Required Fields

- LP organization.
- Program title.
- Source URL.
- Status.
- Confidence status.

### Relationships

- LP to Organization.
- Program to selected GP.
- Program to News/Report source.

### Gaps

- Not built.

## Entity: Report

### User-Facing Meaning

Law firm memos, accounting firm reports, regulator guides, adviser reports, and
other reusable reference materials.

### Proposed Tables

```sql
report_document (
    report_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    publisher TEXT,
    report_type TEXT,
    published_date TEXT,
    source_url TEXT NOT NULL,
    local_path TEXT,
    content_hash TEXT,
    summary TEXT,
    review_status TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
)
```

```sql
report_entity_link (
    link_id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    entity_name TEXT NOT NULL,
    link_confidence TEXT,
    notes TEXT
)
```

### Relationships

- Report to GP.
- Report to Deal.
- Report to LP.
- Report to Wiki/Guide.

### Gap

- Currently reports can be stored as `news_document.document_type = 'report'`
  short term, but a separate report table is better once volume grows.

## Generic Evidence Table: Future Consolidation

Current evidence is split by source type. That is acceptable for now.
Long term, use a generic evidence table:

```sql
entity_evidence (
    evidence_id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_name TEXT,
    evidence_value TEXT,
    source_type TEXT,
    source_title TEXT,
    source_url TEXT,
    source_grade TEXT,
    verification_status TEXT,
    captured_at TEXT,
    notes TEXT
)
```

This should not replace raw source tables. It should summarize verified facts
used by the service.

## Recommended Implementation Order

### Step 1: Data Quality Layer

Add flags or export reports for:

- GP profile confidence.
- Fund same-name ambiguity.
- GP changed by fund.
- Commitment amount jumps.
- Fund disappearance/reappearance.
- Missing official source for top GP profile.

### Step 2: People DB First Load

Now that the empty schema and CSV import path exist, load and review one GP team
before scaling.

Use:

- `person`
- `person_role`
- `person_education`
- `person_source`

Then test with one GP team page before scaling.

### Step 3: Deal DB Foundation

Create:

- `organization`
- `deal`
- `deal_party`
- `deal_fund_link`
- `deal_adviser`

Then use daily news output to produce deal candidates.

### Step 4: Report Library

Create:

- `report_document`
- `report_entity_link`

Then link law firm/accounting firm/regulator materials to GP, Deal, LP, and Wiki
topics.

### Step 5: LP Program DB

Create:

- `organization` rows for LPs.
- `lp_program`
- `lp_program_selection`

Only after GP and Deal models are stable enough to link selected GP records.

## Practical Rule For New Work

When adding a new crawler or manual dataset, decide first:

- Which entity does this create or update?
- Which stable ID will it use?
- Which source evidence records will it write?
- Which fields are verified, source-derived, or review-needed?
- Which dashboard or newsletter view will use it?

If those questions cannot be answered, do not build the crawler yet.
