# Public Design System

## Product Direction

The public service should feel like an institutional data directory, not a
marketing site or an internal operations dashboard. Use InnoForest-style density:
clear rows, searchable directories, source-backed numbers, and restrained visual
weight.

Newsletter is the current reference implementation for the shared public visual
system. LP, GP, and Wiki screens should converge toward the same shell,
typography, row density, icon treatment, and navigation hierarchy.

## Cross-Service Contract

- The service should feel like one product. Brief, LP, GP, and Wiki must not use
  separate visual tones.
- Build mobile-first. Desktop should extend the mobile structure with a
  restrained content width, not become a different dashboard.
- Public screens must not expose operator wording, source-field names, generation
  notes, or process explanations. Follow the public wording rules in
  `docs/agent_operating_briefs.md`.
- Use white background, neutral text, thin borders, and structured rows before
  reaching for shadows, panels, or heavy cards.
- GP and LP are data directories. Their default shape is a table-like row
  system, not card stacks.
- Wiki is a help-center/documentation surface. Its default shape is body text,
  table of contents, internal anchors, and related references.

## View Taxonomy

Use one of these view types before designing or changing a public screen.

- Article list view: for daily/weekly brief articles. Use flat rows, section
  labels, publisher metadata, restrained tags, and circular publisher icons.
  Do not use table columns or card grids for ordinary article lists.
- Directory table view: for GP and LP lists. Use table-like rows with comparable
  columns, sorting/filter controls, circular CI/logo slots, and compact numeric
  facts. Do not show entity-type badges under names when those values are only
  useful as filters.
- Profile detail view: for GP and LP entity pages. Use a calm identity header,
  fact matrix, history/news/connection tables, source-linked sections, and
  quiet typography. Avoid repeating generic row actions like `상세 프로필`.
- Notice row-card view: for LP official notices and similar long-title workflow
  items. Use row cards or table-like cards because notice titles, deadlines,
  institutions, attachments, and source links need more room than a compact
  directory row. Keep cards flat and operationally useful; do not turn notices
  into marketing cards.
- Document view: for Wiki. Use title, body text, table of contents, anchors,
  related law/regulation links, and source references. Use tables only when the
  source content is naturally tabular.

If a screen mixes two view types, split it into tabs or pages instead of forcing
both into one surface. For example, LP directory and official notices should be
separate `LP` and `NOTICE` tabs/pages.

## Data Refresh Model

The public service is currently a static generated site. Source data lives in
the DB, CSV files, exports, and crawler outputs, but public pages are generated
HTML files at build time.

- A crawler, DB import, or CSV edit changes the source data only.
- The public website changes only after the site builder regenerates the static
  HTML and the generated site is published to GitHub Pages.
- Numbers such as article counts, LP notice counts, GP counts, AUM/commitment
  metrics, and profile counts are not hand-coded in the source renderer. They
  are read from source data during the build and then baked into the generated
  HTML for that deployment.
- Do not manually edit generated public HTML to update numbers. Fix or update
  the source data/renderer, rebuild, verify, and publish.
- When explaining freshness to non-developers, say: "DB update is the
  ingredient; build/deploy is what puts it on the website."

## Navigation

- Use one global bottom nav order everywhere: `브리프 / LP / GP / Wiki`.
- Do not add top-level service tabs above public content.
- Page-local controls may exist, but they must be scoped to the current screen:
  for example `시장 / GP / 펀드 / LP / 비교` inside `db.html`.
- The same bottom nav should appear on mobile and desktop.
- `저장` is not a global tab until saved items work across news, LP profiles, GP
  profiles, and Wiki documents. Do not show news-only bookmark controls in the
  public newsletter until there is a clear cross-service saved-items destination.

## Visual Rules

- Background: `#ffffff` for pages, `#f7f7f8` only for full-bleed separators or
  muted controls.
- Surface: `#ffffff`
- Muted surface: `#f7f7f8`
- Primary text: `#171717`
- Secondary text: `#737373`
- Tertiary text: `#a3a3a3`
- Border: `#e5e5e5`
- Strong border: `#d4d4d4`
- Accent: black/neutral unless a color encodes status.

Use borders and whitespace before shadows. Avoid decorative gradients, large hero
blocks, nested cards, and card-heavy directory screens.

## Shared Tokens

Use these values as the public UI baseline before introducing service-specific
variants.

- CSS variables: `--bg #f7f7f8`, `--surface #ffffff`,
  `--surface-muted #f7f7f8`, `--text #171717`, `--secondary #737373`,
  `--tertiary #a3a3a3`, `--separator #e5e5e5`, `--accent #171717`.
- Mobile page gutter: `14-16px`.
- Desktop reading/list width: `860-900px`.
- Row divider: `1px solid #e5e5e5` or a lower-opacity equivalent when rows are
  dense.
- Section band: full-bleed `#f7f7f8`, about `8px` high, with compact vertical
  spacing.
- List icon/logo slot: circular `40px`, top-aligned for multi-line rows.
- Bottom nav: fixed, same order everywhere, label about `11-12px`, icon about
  `18-23px`, active state neutral.

## Typography

- Font stack: `Pretendard`, `Pretendard Variable`, `Noto Sans KR`,
  `Apple SD Gothic Neo`, `Malgun Gothic`, `system-ui`, `sans-serif`
- Do not scale font size with viewport width.
- Letter spacing should be `0`.
- Product/page title on mobile should usually be 21-28px. Use 32-38px on PC only
  for true page titles.
- Service tabs should usually be 13px.
- Section labels should usually be 12.5-14.5px.
- Data labels, counts, tags, and metadata should usually be 11-13px.
- Directory row titles should usually be 15-16px.
- Newsletter article titles should usually be about 15px with medium-bold weight,
  not hero-scale type.
- Reserve large headings for true page titles only.

## Public Shell

- Header uses one compact title row with only necessary utility icons.
- Search opens inside the header, not as a separate card or floating panel.
- Page-local tabs use text tabs with a thin neutral baseline and a black active
  underline. Disabled/future tabs stay low-contrast.
- Bottom nav is the only global service navigation and must stay in the order
  `브리프 / LP / GP / Wiki`.
- Desktop keeps the same navigation hierarchy; it may render as a lighter centered
  pill but should not become a different product shell.

## Directory Patterns

- GP and LP directory screens should be table-like.
- Desktop directories should expose comparable columns in one row.
- Mobile directories may collapse to compact rows, but should still read as a
  list rather than a stack of promotional cards.
- Mobile directories should not rely on wide horizontal scrolling. If all
  columns cannot fit, choose the most important columns instead.
- Rows should use a circular CI/logo slot. If no public logo is available, use a
  same-size restrained monogram fallback.
- Primary row actions should lead to detail, source, compare, or connected
  records.
- Public rows should not expose internal enum values or pipeline terminology.
- Do not display `ownership_type` or `public/private` style values inside the LP
  or GP name cell. Use them as filters only.
- Avoid repeated row text such as `상세 프로필` when the whole row already links
  to detail.
- Do not repeat rank, category, or source information in multiple places inside
  the same row.
- Newsletter article lists should use a white page background and flat row
  dividers, not a gray shell with rounded card containers.
- Newsletter row dividers should be sparse and subtle; avoid stacking top
  borders, date separator lines, and per-row dividers so the page does not read
  as ruled paper.
- Row logos and publisher marks should sit in circular logo slots, not rounded
  square containers.
- Newsletter top tabs may remain as placeholders for planned views, but inactive
  tabs should be low-contrast text tabs rather than heavy disabled controls.
- Bottom navigation is reserved for primary service destinations. Keep it to
  Brief, LP, GP, and Wiki until saved items work across news, LP profiles, GP
  profiles, and wiki documents. News-only saved/bookmark controls should stay
  hidden from the public newsletter until that destination exists.

## Row Anatomy

- Rows use a circular 40px logo slot, primary title, secondary metadata, and
  restrained contextual tags.
- Multi-line rows align the logo slot near the top of the row.
- Row titles should be strong enough to scan, but not headline-sized. Use about
  `15-16px` and `590-650` weight depending on density.
- Avoid right-side icons unless they are high-value actions with a visible
  destination. Removing low-value actions is preferred to adding visual noise.
- Tags stay one line by default; overflow uses a quiet text-like `더보기 N`
  control.

## Section Bands

- Use full-bleed muted bands to separate large content groups without wrapping
  each group in a card.
- Do not pair full-bleed bands with excessive top/bottom whitespace.
- Do not add section count badges unless the count materially changes user
  behavior.

## Newsletter Reference Pattern

Use the newsletter screen as the reference for shared public UI polish.

- Background: white page background.
- Content layout: flat grouped list, not gray card containers.
- Mobile side padding: 14-16px.
- PC reading width: about 860-900px.
- Header: compact title row with utility icons. Search opens inside the header.
- Top tabs: `Daily / Weekly / 출자공고` stay as future placeholders. Inactive tabs
  are low-contrast text tabs. The tab row uses a thin neutral baseline, and the
  selected tab uses a clearly visible black underline.
- Date control: compact centered pill, no decorative horizontal side lines. On
  the newsletter, the active date may be the single black emphasis element with
  white text.
- Section label: visible but restrained. Current reference is about 14.5px, 760
  weight. When category separation is weak, prefer a
  clearer section label and a quiet full-bleed neutral band between sections
  rather than wrapping each category in a card. Do not show section count badges
  in the public newsletter list.
- Article title: about 15px, medium-bold, two-line clamp.
- Publisher/meta: secondary information, visually lower than title.
- Publisher icon: circular 40px slot, aligned toward the top of the article row
  rather than vertically centered.
- Public logo slots for news publishers, LPs, and GPs must use the same visual
  treatment: circular container, thin neutral border, and favicon or CI centered
  inside. Logo-backed slots default to white like InnoForest/TheVC directory
  rows. Use curated domain-based brand backgrounds for known solid-color marks
  such as NAVER or Hankyung instead of forcing every logo into a gray circle.
  Scale favicon images to the standard inner size instead of preserving tiny
  natural favicon dimensions. Do not draw a second inner ring inside the slot.
- Tags: one-line by default. Use a small text-like `더보기 N` control when tags
  overflow. Do not use dark pill buttons for hidden tags.
- Row dividers: sparse 1px neutral separators only between rows. Avoid stacked
  top borders, date separator lines, and last-row borders.
- Article-row bookmarks are not shown in the public newsletter list. Avoid
  right-side save icons unless saved items become a cross-service feature with a
  clear destination.

## LP And GP Application

- Align LP and GP directory pages to the newsletter reference for density,
  typography, neutral palette, and row rhythm.
- LP/GP list pages should show comparable facts in table-like rows: name,
  latest/rank signal, key amount/count, and relevant connection.
- News, LP, and GP list rows should share the same 40px circular logo-slot
  treatment. Detail hero logos may be larger, but must keep the same muted
  container, neutral border, and favicon blending behavior.
- Detail pages should use fact matrix, history/news tables, source-linked
  sections, and quiet typography.
- LP detail pages follow this public reading order: identity header, basic
  institution facts, investment status, official notices, related GP, related
  news, peer comparison, then source/reference links. Keep coverage counts and
  source diagnostics out of the top summary.
- LP detail pages should not expose collection coverage as product content.
  Avoid public rows such as `자료 성격`, `프로필 항목`, or repeated source-status
  labels. Put source links and narrow caveats in the bottom `자료` area only.
- LP detail headers should not use generic explanatory copy such as "we organize
  basic information and news." Follow data services like Preqin, The VC, and
  InnoForest: show the entity name, compact identity facts, tabs, and immediate
  data sections.
- LP profile data should prioritize: institution type and address, AUM/total
  assets, current and target allocation, strategy or asset-class preferences,
  historical commitments and official notices, known GP relationships,
  decision-makers and consultants when public, resources/RFPs/minutes/reports,
  and directly related news.
- Profile fact rows should not print long source strings such as source name,
  date, and confidence under every value. When a fact needs a public source
  link, use a small icon-only link for homepage, document, article, or LinkedIn
  and keep verbose source lists in the bottom reference section.
- Avoid marketing hero layout, oversized titles, repeated KPI cards, and
  operator-facing explanations.
- Use page-local filters and sorting. Do not let a large list become endless
  unstructured scrolling.
- GP directory rows should stay compact: circular logo, GP name, representative
  or homepage on desktop, rank/commitment facts, and news/LP connection counts.
  Do not add repeated `상세 프로필`, row-level accordions, or right-side utility
  icons unless the action has a clear cross-service destination.
- GP detail pages should use quiet fact matrices and linked history/news lists.
  Keep the order as identity, operating facts, fund history, LP connections,
  deal/news context, and peer links.

## GP Reference Pattern

- GP must reuse the newsletter public shell tokens: white page background,
  neutral text, `#e5e5e5` dividers, circular CI/logo slots, and the unified
  bottom nav.
- GP directory rows should behave like a compact data table. Mobile keeps
  logo/name/rank-or-amount visible; desktop may add representative/homepage,
  fund metrics, news, deal, and LP counts.
- Do not show repeated row actions such as `상세 프로필` or vague actions such as
  `보기` when the GP name already links to the profile.
- Avoid pill-heavy metadata in GP rows. Category, verification, and
  public/private style attributes should be quiet filters or detail facts, not
  prominent row badges.
- GP detail pages should use a simple identity header, fact matrix, fund history,
  LP connection, deal/news tables, and quiet disclaimer text.
- Public GP screens must not expose internal labels such as `AI-generated`,
  `operator`, `proxy`, `research`, `verification`, `source/evidence`, `상위 프로필`,
  or `자료 확인`. AI as a quoted news topic or industry term is allowed. Use public
  labels such as `운용 현황`, `약정액 기준`, `출자 연결`, and `관련 뉴스`.
- GP directory filters should stay short and user-facing. Prefer `전체`, `운용 중`,
  `뉴스`, `딜`, and `출자`; do not expose build coverage, verification state, or
  profile-page availability as visible filters.
- GP CSS should be kept in a single canonical public style block over time.
  Temporary override blocks, duplicate selector drift, and unused old card styles
  should be removed when a screen is next edited.

## Wiki Application

- Wiki should follow OpenAI Help/Google Help-style documentation: title, short
  subtitle, body text, sidebar or drawer table of contents, internal anchors, and
  related references.
- Do not make Wiki a card gallery, PDF link page, or conversational summary.
- Use tables only when the underlying content is naturally tabular.
- Keep body typography calmer than data directories; avoid excessive bold and
  excessive horizontal rules.

## Regression Checklist

- Bottom nav labels are exactly `브리프 / LP / GP / Wiki`.
- Newsletter keeps flat list structure, circular publisher icons, restrained
  section labels, and non-heavy article titles.
- LP/GP list pages preserve table-like row structure and do not regress to
  card-heavy layouts.
- Mobile width around 390px has no incoherent horizontal overflow.
- PC width around 1280px does not stretch reading lists beyond the intended
  column width.
- No public page exposes `관리자`, `operator`, `자동 생성`, `source/evidence`,
  `AUM proxy`, or other internal wording unless it is part of a quoted source
  title.

## Verification

Run this before publishing public frontend changes:

```bash
python3 scripts/check_public_frontend.py
```

Frontend work is not complete until the source renderer is changed, generated
site output is rebuilt, this checker passes, and 390px/1280px views have been
checked for overflow and menu consistency.

Use the deployed smoke check when publishing to GitHub Pages:

```bash
python3 scripts/check_public_frontend.py --base-url https://pkkong.github.io/kpef-newsletter/
```
