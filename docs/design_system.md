# Public Design System

## Product Direction

The public service should feel like an institutional data directory, not a
marketing site or an internal operations dashboard. Use InnoForest-style density:
clear rows, searchable directories, source-backed numbers, and restrained visual
weight.

## Navigation

- Use one global bottom nav order everywhere: `브리프 / LP / GP / Wiki / 저장`.
- Do not add top-level service tabs above public content.
- Page-local controls may exist, but they must be scoped to the current screen:
  for example `시장 / GP / 펀드 / LP / 비교` inside `db.html`.
- The same bottom nav should appear on mobile and desktop.

## Visual Rules

- Background: `#ffffff`
- Surface: `#ffffff`
- Muted surface: `#fafafa`
- Primary text: `#171717`
- Secondary text: `#737373`
- Border: `#e5e5e5`
- Strong border: `#d4d4d4`
- Accent: black or neutral unless a color encodes status.

Use borders and whitespace before shadows. Avoid decorative gradients, large hero
blocks, nested cards, and card-heavy directory screens.

## Typography

- Font stack: `Pretendard`, `Pretendard Variable`, `Noto Sans KR`,
  `Apple SD Gothic Neo`, `Malgun Gothic`, `system-ui`, `sans-serif`
- Do not scale font size with viewport width.
- Letter spacing should be `0`.
- Data labels and metadata should usually be 11.5-13px.
- Directory row titles should usually be 14-16px.
- Reserve large headings for true page titles only.

## Directory Patterns

- GP and LP directory screens should be table-like.
- Desktop directories should expose comparable columns in one row.
- Mobile directories may collapse to compact rows, but should still read as a
  list rather than a stack of promotional cards.
- Primary row actions should lead to detail, source, compare, or connected
  records.
- Public rows should not expose internal enum values or pipeline terminology.
- Newsletter article lists should use a white page background and flat row
  dividers, not a gray shell with rounded card containers.
- Row logos and publisher marks should sit in circular logo slots, not rounded
  square containers.
- Newsletter top tabs may remain as placeholders for planned views, but inactive
  tabs should be low-contrast text tabs rather than heavy disabled controls.

## Verification

Run this before publishing public frontend changes:

```bash
python3 scripts/check_public_frontend.py
```

Use the deployed smoke check when publishing to GitHub Pages:

```bash
python3 scripts/check_public_frontend.py --base-url https://pkkong.github.io/kpef-newsletter/
```
