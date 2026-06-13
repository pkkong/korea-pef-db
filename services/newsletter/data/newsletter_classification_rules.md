# KPEF Newsletter Classification Rules

This document is the reference source for NotebookLM-assisted newsletter review.
Use one representative section per article. Classify by the main subject, not by
incidental keywords, quoted words, or secondary context.

## Output Contract

Return strict JSON only.

```json
{
  "articles": [
    {
      "news_id": "same news_id from source pack",
      "section_suggestion": "AI_PE | NationalGrowthFund | Deal | LP | GP | Market",
      "summary_lines": ["line 1", "line 2", "line 3"],
      "short_summary_100": "100자 이내 핵심 요약",
      "gp_names": [],
      "lp_names": [],
      "deal_targets": [],
      "confidence": 0.0,
      "notes": "분류 근거 1문장"
    }
  ]
}
```

## Section Definitions

### AI_PE

Use `AI_PE` only when AI is the main investment or private-market theme itself.
Examples include AI infrastructure investment theses, AI software disruption in
private equity, AI-native buyout opportunities, or AI-related private market
capital flows.

Do not use `AI_PE` just because the article mentions AI inside a GP fundraising
story, a national fund mandate, or a specific company financing.

### NationalGrowthFund

Use `NationalGrowthFund` when the national growth fund program itself is the
main subject. Examples include national growth fund mandate announcements,
selection rounds, allocation structure, GP selection result, or public fund
policy around the program.

If the article is mainly about a GP using national growth fund selection to
raise a vehicle, classify it as `GP`.

### Deal

Use `Deal` for specific transactions. Examples include acquisition, sale,
merger, carve-out, IPO, block trade, CB/BW/mezzanine financing, project
financing, minority investment, or company-level capital raise.

If a company receives investment from financial investors, classify it as
`Deal`, unless the article is mainly about the GP's fund strategy.

### LP

Use `LP` for allocator activity. Examples include pension fund, mutual aid,
policy bank, sovereign wealth fund, insurance company, or public fund allocation
decisions, CIO changes, mandate selection, OCIO, commitment planning, or LP
governance.

Do not classify a dispute as `LP` just because a fund investor is mentioned.

### GP

Use `GP` for asset managers and investment firms. Examples include fund closes,
new fund starts, GP fundraising, GP strategy, GP personnel, manager performance,
license updates, or GP-level portfolio construction.

If a GP name appears only as an investor in a specific company transaction,
classify by the transaction as `Deal`.

### Market

Use `Market` for regulation, market structure, policy commentary, private credit
market commentary, conferences, association activity, litigation/governance
themes, or broad trend pieces without one specific deal, LP mandate, or GP event
as the main subject.

## Known Error Boundaries

- `국민성장펀드 잡은 IMM...레버리지는 없다`: `GP`, because the main subject is GP fundraising strategy.
- `대신PE AI·반도체 4000억 펀드 시동`: `GP`, because the main subject is a GP blind fund raise.
- `엑시나 2000억 투자유치`: `Deal`, because the main subject is a company financing.
- `GP 스테이크`: `Market`, when the article discusses the GP stake market structure.
- `사모대출 시장 경고등`: `Market`, when it is market commentary rather than a specific financing.
- `법원, 고려아연에 투자 문서 제출 명령`: `Market`, when the main subject is litigation or governance.

## Summary Style

Write Korean memo-style fragments for investment professionals.

- Prefer 2-3 short lines.
- Line 1: event.
- Line 2: parties, amount, status, or timing.
- Line 3: why it matters for PE, LP, GP, or market readers.
- Avoid casual newsletter tone.
- Avoid endings such as `했다`, `한다`, `전망이다`, `사례다`, `했어요`, `입니다`.
- Do not repeat the article title.
