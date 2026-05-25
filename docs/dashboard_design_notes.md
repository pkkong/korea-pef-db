# Dashboard Design Notes

## Reference Services Checked

- THE VC: Korean company/investor profile pages use a clear profile header, tabs, company overview, key information, recent news, investment/fund tables, peer comparison, and source-sensitive locked data patterns.
- Preqin Pro: GP profiles are organized around overview, contacts, investment strategy, funds/performance, investors, deals/assets, lead partners, service providers, and sustainability.
- Bloomberg Private Equity: The product framing emphasizes fast search, news/data/analytics integration, due diligence, benchmarking, monitoring, and portfolio/risk analysis.
- S&P Capital IQ Pro: Private markets intelligence emphasizes broad entity coverage, market maps/topic tags, company/fund intelligence, and workflow-oriented research.
- Sankun: Public landing emphasizes database categories, strong search, "anyone can use it" positioning, large data coverage metrics, and clear entry points such as company DB, site DB, bidding DB, reputation DB, and news DB.

## Product Direction For This Project

The dashboard should not behave like a simple chart page. It should behave like a lightweight private-markets terminal:

1. Market context first: latest period, active PEF count, active GP count, commitment proxy AUM, new fund formation, top-house concentration.
2. Search is central: GP names, Korean legal names, English names, and aliases should resolve to one canonical GP profile.
3. GP profile is the core unit: basic legal info, source quality, active funds, AUM trend, cumulative AUM, and news-driven maintenance status should be visible from one profile surface.
4. Ranking and peer comparison are always nearby: users should move from market rank to house detail without leaving the page.
5. Evidence quality is explicit: distinguish official-source profile data from FSS-name-only entities and show remaining gaps instead of guessing.
6. The dashboard must remain deployable: HTML, CSS, JS, and generated JSON are separated, with data built by scripts rather than manual edits.
7. Public mobile UX should not mix market overview and GP detail in one dense screen. Use separate surfaces: home, market, GP, and compare.

## Current Implementation

- App shell: `dashboard/index.html`
- Template: `dashboard/index_app_template.html`
- Styles: `dashboard/assets/app.css`
- Client logic: `dashboard/assets/app.js`
- Generated data: `dashboard/data/dashboard_data.json`
- Data builder: `scripts/build_dashboard_data.py`
- Refresh pipeline: `scripts/run_pipeline.py`

## Next Visual Iterations

- Add a real GP profile route later, for example `/gp/mbk-partners`, when the project moves from local dashboard to server app.
- Add deal/person/LP tabs only after those databases are reliable enough to avoid empty product surfaces.
- Add exported screenshots/PDF reports only after the on-screen layout stabilizes.
- Convert the current public tab views into real routes later: `/market`, `/gp/:slug`, and `/compare`.
