# Korea PEF Intelligence Service Structure

## Purpose

This service should become the central Korea institutional PEF intelligence portal.
The product is not just a dashboard. It is a connected database and publishing
system covering GP houses, funds, people, deals, LPs, news, reports, and practical
PEF reference materials.

The service should answer user questions first, then expose the underlying data.
The corresponding entity data dictionary is maintained in `entity_data_model.md`.

## Product Principles

- Start from high-value questions users actually ask.
- Keep every displayed number traceable to a source.
- Separate verified facts, source-derived facts, and review-needed records.
- Prefer tables for dense financial data and lists/cards only for summaries.
- Make updates repeatable through source files, scripts, and evidence rows.
- Avoid one-off manual edits that cannot be regenerated.

## Primary Navigation

### 1. Market

User question:

- How large is the Korean institutional PEF market?
- Which GP is currently large or growing?
- Which year or quarter had meaningful new fund formation?

Core views:

- Market overview by quarter.
- GP AUM ranking.
- New PEF formation by year and quarter.
- Top GP concentration.
- Fastest growing or shrinking GP by quarter.

Core data:

- FSS quarterly PEF disclosure source files.
- Fund-by-period snapshots.
- GP-by-period AUM aggregates.
- Fund formation and liquidation signals.

Current status:

- Mostly available through the FSS PEF pipeline.
- Needs quality flags and anomaly review before user-facing confidence labels.

### 2. GP DB

User question:

- What is this GP?
- How large is it?
- Which funds does it manage?
- Who works there?
- What news, deals, and source documents are connected to it?

Core views:

- GP profile page.
- Current and cumulative AUM.
- Active and historical fund table.
- Company information and identifiers.
- People connected to the GP.
- Deals connected to the GP.
- News and report timeline.
- Source evidence and data quality status.

Core data:

- GP canonical name.
- Aliases and historical names.
- Legal entity name.
- Business registration number.
- Corporate registration number.
- Financial registration number when available.
- Website, representative, address, phone, established date.
- Source-backed profile evidence.
- Linked funds, people, deals, news, and reports.

Current status:

- GP master and GP profile master exist.
- Top GP profile coverage is usable, but not final.
- People and deal links are not yet built.

### 3. Fund DB

User question:

- What is this fund?
- Who manages it?
- When was it formed?
- How large is it?
- Is it active or liquidated?
- Did the GP name or commitment amount change over time?

Core views:

- Fund search table.
- Fund detail page.
- Quarterly commitment history.
- GP history and raw GP name history.
- Formation and liquidation status.
- Review flags for unusual records.

Core data:

- Fund master.
- Fund name normalization.
- Established date.
- Latest, first, and max commitment amount.
- Active/latest status.
- Quarter-by-quarter snapshots.
- Raw GP names and canonical GP names.

Current status:

- Fund master exists.
- Needs validation report for same-name funds, GP changes, commitment jumps,
  and source-level anomalies.

### 4. People DB

User question:

- Who are the key people in each GP?
- What is their background?
- Which deals or sectors are they connected to?
- How senior are they and what is their likely career cohort?

Core views:

- People directory.
- Person profile page.
- GP team page.
- Career timeline.
- Education and prior employer table.
- Source links.

Core data:

- Name.
- Current GP.
- Title or role.
- Team or function.
- Education.
- Previous employers.
- Career history.
- Social/profile links.
- News mentions.
- Linked deals.
- Age-cohort fields only when source-backed.

Rules:

- Do not infer birth year, class year, or age cohort without credible source.
- If only weak social evidence exists, mark source level clearly.
- Empty is better than guessed.

Current status:

- People DB foundation exists.
- Repeatable CSV inputs and source evidence tables are ready.
- Premier Partners and MBK Partners teams have been loaded from official team pages.
- Public GP detail page now shows linked People table and person-level career/education detail.

### 5. Deal DB

User question:

- Which GP bought or sold which company?
- What was the deal size?
- Who advised the transaction?
- Which people, law firms, accountants, and lenders were involved?

Core views:

- Deal search table.
- Deal detail page.
- GP deal history.
- Target company history.
- Adviser leaderboard.
- Sector and year filters.

Core data:

- Target company.
- Buyer and seller.
- GP or fund involved.
- Deal type.
- Announced or closed date.
- Deal amount.
- Equity value or enterprise value when available.
- Stake percentage.
- Sector.
- Legal adviser, accounting adviser, financial adviser.
- News/report/source links.

Current status:

- Not built.
- Should start with news-derived deal candidates, then review and normalize.

### 6. News / Reports

User question:

- What happened today in Korean PEF?
- Which GP requires profile or deal update because of new news?
- What reports or law firm/accounting firm materials are worth saving?

Core views:

- Daily clipping.
- Weekly deep-dive candidates.
- GP-linked news timeline.
- Report library.
- Review queue for DB updates.

Core data:

- Source, title, URL, published date.
- Matched GP names and aliases.
- Category.
- Editorial quality score.
- Include/exclude review status.
- Suggested DB update action.

Current status:

- Daily news MVP exists.
- GP update worklist exists.
- Needs stronger review workflow and report-library schema.

### 7. LP / Commitments

User question:

- Which LPs are allocating to private equity?
- Which GP won which mandate?
- What are the investment themes, selection criteria, and ticket sizes?

Core views:

- LP directory.
- LP commitment program page.
- 출자사업 공고/선정 결과 table.
- Selected GP history.
- LP organization and 담당팀 information where source-backed.

Core data:

- LP name.
- LP category.
- AUM or alternative allocation when available.
- RFP title.
- Commitment size.
- Strategy.
- Application and selection dates.
- Selected GP.
- Source documents.
- 담당 조직 and 담당자 only when publicly source-backed.

Current status:

- Not built.
- Should be built after GP/Fund confidence layer is stable.

### 8. Wiki / Practical Guides

User question:

- How does institutional PEF regulation work?
- How do FSS reports, tax rules, and fund operation checklists work?
- What should practitioners check?

Core views:

- Regulation guide.
- FSS reporting guide.
- Tax guide.
- PEF workbook.
- Checklist library.
- Glossary.

Core data:

- Law/regulation references.
- FSS guide materials.
- Tax authority materials.
- Internal commentary and examples.
- Last reviewed date.

Current status:

- Not built.
- Should be built as source-linked markdown first, not as a complex app.

## Cross-Entity Links

The long-term value comes from connecting entities, not just storing tables.

Required relationships:

- GP to Fund.
- GP to Person.
- GP to Deal.
- GP to News.
- GP to Report.
- Fund to GP.
- Fund to Deal.
- Deal to Target Company.
- Deal to Adviser.
- LP to Commitment Program.
- Commitment Program to Selected GP.
- News to GP, Fund, Deal, Person, LP, and Adviser.

## Confidence Levels

Every major record should have a visible confidence level.

- `verified`: confirmed by official or authoritative source.
- `source_derived`: directly derived from FSS, article, company page, or report.
- `review_needed`: likely useful but needs human review.
- `inferred_low_confidence`: should generally not be shown publicly unless clearly labeled.
- `unknown`: leave blank rather than guessing.

## Suggested Build Order

### Near Term

1. Stabilize public information architecture around Ranking, GP Detail, Fund Table, and Compare.
2. Add data quality flags to GP and Fund outputs.
3. Build fund master validation report.
4. Improve GP profile evidence workflow for news-visible top GPs.
5. Extend daily news review queue into GP/Fund/Deal update candidates.

### Mid Term

1. Load and review one GP team through the People DB input path.
2. Build Deal DB candidate extraction from news and reports.
3. Add GP page sections for People, Deals, News, and Reports.
4. Add report library for law firm, accounting firm, regulator, and adviser materials.

### Later

1. Build LP and commitment program DB.
2. Build Wiki and practical guide section.
3. Add account, saved list, alerts, and newsletter subscription features if service moves beyond local prototype.

## Current Product Boundary

The current working product should be treated as an operator-assisted prototype.

Public-facing enough:

- Market size by quarter.
- GP AUM ranking.
- GP profile for top/service-ready GPs.
- Active fund table.
- Peer comparison.
- Daily clipping output.

Not public-facing yet:

- Long-tail GP profiles without source confidence.
- Fund records with unresolved anomaly flags.
- People profiles without repeatable evidence model.
- Deal records before normalized deal schema exists.
- LP 담당자/personnel information unless publicly source-backed and reviewed.
