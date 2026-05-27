#!/usr/bin/env python
"""Render static PEF Wiki pages for the newsletter site."""

from __future__ import annotations

import json
from html import escape as html_escape


PEF_WIKI_SOURCE_TITLE = "기관전용 사모집합투자기구 실무안내, 2023.06"
SOURCE_URLS = {
    "fss": "https://www.fss.or.kr/",
    "law": "https://www.law.go.kr/",
    "kdi": "https://eiec.kdi.re.kr/policy/materialView.do?num=240321",
    "kvca": "https://www.kvca.or.kr/Program/board/listbody.html?a_cd=12&a_gb=board&a_item=0&page=1&po_no=6352&sm=4_3&tm_num=3",
    "kvca_pdf": "https://www.kvca.or.kr/files/download.html?a_cd=12&a_gb=board&file=6352_1688103776.pdf&name=%EA%B8%B0%EA%B4%80%EC%A0%84%EC%9A%A9+%EC%82%AC%EB%AA%A8%EC%A7%91%ED%95%A9%ED%88%AC%EC%9E%90%EA%B8%B0%EA%B5%AC+%EC%8B%A4%EB%AC%B4%EC%95%88%EB%82%B4_230629.pdf",
}
APP_ICON_FILE = "apple-touch-icon.png"

REFERENCE_LINKS = {
    "institutional_private_fund": {
        "label": "기관전용 사모집합투자기구",
        "type": "용어",
        "location": "원문 제1장 제2절 p.10",
        "source_label": "KVCA 첨부 PDF",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["general_vs_institutional", "gp", "lp"],
    },
    "capital_markets_act": {
        "label": "자본시장법",
        "type": "법령",
        "location": "국가법령정보센터 현행 법령",
        "source_label": "국가법령정보센터",
        "source_url": SOURCE_URLS["law"],
        "related": ["fss_reporting", "gp"],
    },
    "general_vs_institutional": {
        "label": "일반 사모 / 기관전용 사모",
        "type": "분류",
        "location": "원문 제1장 제2절 p.10 · KDI 정책자료",
        "source_label": "KDI 정책자료",
        "source_url": SOURCE_URLS["kdi"],
        "related": ["institutional_private_fund"],
    },
    "gp": {
        "label": "업무집행사원(GP)",
        "type": "역할",
        "location": "원문 제1장 제2절 p.10 · 제3장 GP 등록 제도",
        "source_label": "금융감독원",
        "source_url": SOURCE_URLS["fss"],
        "related": ["lp", "fss_reporting"],
    },
    "lp": {
        "label": "유한책임사원(LP)",
        "type": "역할",
        "location": "원문 제1장 제2절 p.10 · LP 출자공고 서비스",
        "source_label": "KVCA 게시글",
        "source_url": SOURCE_URLS["kvca"],
        "related": ["gp", "institutional_private_fund"],
    },
    "fss_reporting": {
        "label": "설립·변경·해산 보고",
        "type": "규정",
        "location": "원문 관련 장 · 금융감독원 보고 자료",
        "source_label": "금융감독원",
        "source_url": SOURCE_URLS["fss"],
        "related": ["capital_markets_act", "gp"],
    },
    "special_purpose": {
        "label": "특수목적 기관전용 사모펀드",
        "type": "유형",
        "location": "원문 관련 장 · KVCA 첨부 PDF",
        "source_label": "KVCA 첨부 PDF",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["institutional_private_fund"],
    },
}

CHAPTER_SECTIONS = [
    ("chapter", "제1장 개관", "원문 목차"),
    ("background", "제1절 도입 배경", "원문 p.8"),
    ("classification", "제2절 개요 및 분류", "원문 p.10"),
    ("market", "제3절 관련 현황", "원문 p.13"),
    ("history", "제4절 연혁", "원문 p.18"),
    ("rules", "법령·규정", "참조"),
    ("sources", "출처", "공식 링크"),
]


def render_pef_wiki_page(report_date: str) -> str:
    """Return a complete pef-wiki.html document."""
    safe_date = html_escape(report_date)
    refs_json = json.dumps(REFERENCE_LINKS, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>PEF Wiki - 기관전용 사모집합투자기구 실무안내</title>
{_app_head_meta()}
  <link rel="stylesheet" href="assets/service.css">
  {_page_styles()}
</head>
<body>
  <main class="wiki-shell">
    {_render_top_nav()}
    <header class="wiki-hero">
      <div>
        <p class="wiki-kicker">PEF Wiki</p>
        <h1>기관전용 사모집합투자기구 실무안내</h1>
        <p class="wiki-lede">제1장 개관 · 원문 목차 기반</p>
      </div>
      <form class="wiki-search" role="search">
        <label for="wikiSearch">문서 검색</label>
        <input id="wikiSearch" type="search" placeholder="예: GP, LP, 자본시장법, 보고">
      </form>
      <div class="wiki-source-strip" aria-label="공식 출처">
        <a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">원문 PDF</a>
        <a href="{html_escape(SOURCE_URLS["kvca"])}" target="_blank" rel="noreferrer">KVCA 게시글</a>
        <a href="{html_escape(SOURCE_URLS["kdi"])}" target="_blank" rel="noreferrer">KDI 정책자료</a>
        <span>기준일 {safe_date}</span>
      </div>
    </header>

    <div class="wiki-layout">
      <aside class="wiki-sidebar" aria-label="문서 목차">
        <strong>제1장 목차</strong>
        <nav>
{_render_sidebar_links()}
        </nav>
      </aside>

      <article class="wiki-document" aria-label="기관전용 사모집합투자기구 실무안내 제1장">
        <section class="wiki-section" id="chapter" data-search="제1장 개관 기관전용 사모집합투자기구 실무안내 pef">
          <p class="wiki-eyebrow">제1장</p>
          <h2>개관</h2>
          <ol class="wiki-source-index">
            <li><a href="#background">제1절 사모투자전문회사(PEF) 제도 도입 배경</a><span>p.8</span></li>
            <li><a href="#classification">제2절 기관전용 사모집합투자기구 개요 및 분류</a><span>p.10</span></li>
            <li><a href="#market">제3절 기관전용 사모집합투자기구 관련 현황</a><span>p.13</span></li>
            <li><a href="#history">제4절 연혁</a><span>p.18</span></li>
          </ol>
          <div class="wiki-inline-tools" aria-label="주요 참조">
            <button class="wiki-ref" type="button" data-ref="institutional_private_fund">기관전용 사모집합투자기구</button>
            <button class="wiki-ref" type="button" data-ref="general_vs_institutional">일반 사모 / 기관전용 사모</button>
            <button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button>
          </div>
        </section>

        <section class="wiki-section" id="background" data-search="도입 배경 외환위기 기업 구조조정 위험자본 buyout m&a">
          <p class="wiki-eyebrow">제1절</p>
          <h2>사모투자전문회사(PEF) 제도 도입 배경</h2>
          <div class="wiki-source-line">
            <span>원문 위치</span>
            <a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">PDF p.8 열기</a>
          </div>
          <div class="wiki-link-row">
            <button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button>
            <button class="wiki-ref" type="button" data-ref="gp">GP</button>
            <a href="#history">관련 연혁으로 이동</a>
          </div>
        </section>

        <section class="wiki-section" id="classification" data-search="개요 분류 일반 사모 기관전용 사모 GP LP 자본시장법">
          <p class="wiki-eyebrow">제2절</p>
          <h2>기관전용 사모집합투자기구 개요 및 분류</h2>
          <div class="wiki-source-line">
            <span>원문 위치</span>
            <a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">PDF p.10 열기</a>
          </div>
          <dl class="wiki-definition-list">
            <div>
              <dt><button class="wiki-ref" type="button" data-ref="institutional_private_fund">기관전용 사모집합투자기구</button></dt>
              <dd><a href="{html_escape(SOURCE_URLS["kvca_pdf"] + "#page=10")}" target="_blank" rel="noreferrer">원문 PDF p.10</a> · <button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button></dd>
            </div>
            <div>
              <dt><button class="wiki-ref" type="button" data-ref="general_vs_institutional">일반 사모 / 기관전용 사모</button></dt>
              <dd><a href="{html_escape(SOURCE_URLS["kdi"])}" target="_blank" rel="noreferrer">KDI 정책자료</a> · 원문 PDF p.10</dd>
            </div>
            <div>
              <dt><button class="wiki-ref" type="button" data-ref="gp">업무집행사원(GP)</button></dt>
              <dd>원문 제3장 GP 등록 제도 · <a href="gps.html">GP 서비스</a></dd>
            </div>
            <div>
              <dt><button class="wiki-ref" type="button" data-ref="lp">유한책임사원(LP)</button></dt>
              <dd>원문 제1장 제2절 · <a href="lp-notices.html">LP 서비스</a></dd>
            </div>
            <div>
              <dt><button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button></dt>
              <dd><a href="{html_escape(SOURCE_URLS["law"])}" target="_blank" rel="noreferrer">국가법령정보센터</a></dd>
            </div>
          </dl>
        </section>

        <section class="wiki-section" id="market" data-search="관련 현황 시장 현황 LP GP 투자대상 감독당국">
          <p class="wiki-eyebrow">제3절</p>
          <h2>기관전용 사모집합투자기구 관련 현황</h2>
          <div class="wiki-source-line">
            <span>원문 위치</span>
            <a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">PDF p.13 열기</a>
          </div>
          <table class="wiki-table">
            <thead>
              <tr><th>항목</th><th>연결</th></tr>
            </thead>
            <tbody>
              <tr><td>LP</td><td><button class="wiki-ref" type="button" data-ref="lp">LP 참조</button> · <a href="lp-notices.html">LP 서비스</a></td></tr>
              <tr><td>GP</td><td><button class="wiki-ref" type="button" data-ref="gp">GP 참조</button> · <a href="gps.html">GP 서비스</a></td></tr>
              <tr><td>감독·보고</td><td><button class="wiki-ref" type="button" data-ref="fss_reporting">설립·변경·해산 보고</button></td></tr>
              <tr><td>법령</td><td><button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button></td></tr>
            </tbody>
          </table>
        </section>

        <section class="wiki-section" id="history" data-search="연혁 2004 2010 2021 2023 제도 개편">
          <p class="wiki-eyebrow">제4절</p>
          <h2>연혁</h2>
          <div class="wiki-source-line">
            <span>원문 위치</span>
            <a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">PDF p.18 열기</a>
          </div>
          <ol class="wiki-timeline">
            <li><strong>2004년</strong><span>PEF 제도 도입</span></li>
            <li><strong>2021년 10월</strong><span>사모펀드 제도 개편</span></li>
            <li><strong>2023년 6월</strong><span>{html_escape(PEF_WIKI_SOURCE_TITLE)} 발간</span></li>
          </ol>
        </section>

        <section class="wiki-section" id="rules" data-search="법령 규정 감독 보고 설립 변경 해산 특수목적">
          <p class="wiki-eyebrow">참조</p>
          <h2>법령·규정 바로보기</h2>
          <div class="wiki-reference-grid">
            <button class="wiki-reference-row" type="button" data-ref="capital_markets_act"><span>법령</span><strong>자본시장법</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="fss_reporting"><span>규정</span><strong>설립·변경·해산 보고</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="special_purpose"><span>유형</span><strong>특수목적 기관전용 사모펀드</strong></button>
          </div>
        </section>

        <section class="wiki-section" id="sources" data-search="출처 원문 pdf kvca kdi 금융감독원">
          <p class="wiki-eyebrow">출처</p>
          <h2>공식 출처</h2>
          <ul class="wiki-source-list">
            <li><a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">기관전용 사모집합투자기구 실무안내 PDF</a></li>
            <li><a href="{html_escape(SOURCE_URLS["kvca"])}" target="_blank" rel="noreferrer">KVCA 일반자료실 게시글</a></li>
            <li><a href="{html_escape(SOURCE_URLS["kdi"])}" target="_blank" rel="noreferrer">KDI 경제정보센터 정책자료</a></li>
            <li><a href="{html_escape(SOURCE_URLS["fss"])}" target="_blank" rel="noreferrer">금융감독원</a></li>
            <li><a href="{html_escape(SOURCE_URLS["law"])}" target="_blank" rel="noreferrer">국가법령정보센터</a></li>
          </ul>
        </section>
      </article>
    </div>
  </main>
  <aside class="wiki-ref-panel" id="wikiRefPanel" aria-label="참조 상세" aria-live="polite" hidden>
    <button class="wiki-ref-close" type="button" aria-label="닫기"></button>
    <span id="wikiRefType"></span>
    <h2 id="wikiRefTitle"></h2>
    <p id="wikiRefLocation"></p>
    <div class="wiki-ref-related" id="wikiRefRelated"></div>
    <a id="wikiRefSource" href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">공식 출처 열기</a>
  </aside>
  <div class="wiki-ref-backdrop" id="wikiRefBackdrop" hidden></div>
  {_render_bottom_nav()}
  <script>window.KPEF_WIKI_REFERENCES = {refs_json};</script>
  <script>{_page_script()}</script>
</body>
</html>
"""


def _render_sidebar_links() -> str:
    return "\n".join(
        f'          <a href="#{html_escape(anchor)}"><span>{html_escape(label)}</span><small>{html_escape(description)}</small></a>'
        for anchor, label, description in CHAPTER_SECTIONS
    )


def _app_head_meta() -> str:
    return f"""  <meta name="theme-color" content="#111827">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="KPEF Wiki">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <link rel="apple-touch-icon" href="{APP_ICON_FILE}">
  <link rel="icon" type="image/png" href="{APP_ICON_FILE}">
  <link rel="manifest" href="site.webmanifest">"""


def _render_top_nav() -> str:
    return """    <nav class="wiki-top-nav" aria-label="Wiki 내부 이동">
      <a class="active" href="#chapter">개관</a>
      <a href="#background">도입 배경</a>
      <a href="#classification">분류</a>
      <a href="#market">현황</a>
      <a href="#history">연혁</a>
      <a href="#rules">법령·규정</a>
      <a href="#sources">출처</a>
    </nav>"""


def _render_bottom_nav() -> str:
    return """  <nav class="bottom-nav newsletter-only" aria-label="하단 메뉴">
    <a href="index.html">
      <span aria-hidden="true" class="nav-dot nav-icon-brief"></span>
      <strong>브리프</strong>
    </a>
    <a href="lp-notices.html">
      <span aria-hidden="true" class="nav-dot nav-icon-lp"></span>
      <strong>LP</strong>
    </a>
    <a href="gps.html">
      <span aria-hidden="true" class="nav-dot nav-icon-gp"></span>
      <strong>GP</strong>
    </a>
    <a class="active" href="pef-wiki.html">
      <span aria-hidden="true" class="nav-dot nav-icon-wiki"></span>
      <strong>Wiki</strong>
    </a>
    <a href="index.html#saved">
      <span aria-hidden="true" class="nav-dot nav-icon-saved"></span>
      <strong>저장</strong>
    </a>
  </nav>"""


def _page_styles() -> str:
    return """  <style>
    :root {
      --wiki-bg: #f6f7f8;
      --wiki-surface: #ffffff;
      --wiki-soft: #f0f4f5;
      --wiki-text: #17202a;
      --wiki-secondary: #52616f;
      --wiki-tertiary: #7a8793;
      --wiki-line: #d9e1e6;
      --wiki-accent: #1f6b63;
      --wiki-accent-soft: #e7f4f1;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; scroll-padding-top: 74px; }
    body {
      margin: 0;
      background: var(--wiki-bg);
      color: var(--wiki-text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    a { color: inherit; }
    .wiki-shell {
      width: min(1220px, calc(100% - 28px));
      margin: 0 auto;
      padding: 12px 0 calc(106px + env(safe-area-inset-bottom));
    }
    .wiki-top-nav {
      position: sticky;
      top: 0;
      z-index: 24;
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding: 8px 0 10px;
      background: rgba(246, 247, 248, 0.94);
      backdrop-filter: blur(14px);
    }
    .wiki-top-nav a {
      flex: 0 0 auto;
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      border-bottom: 2px solid transparent;
      padding: 7px 8px;
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }
    .wiki-top-nav a.active {
      border-color: var(--wiki-accent);
      color: #164c46;
    }
    .wiki-hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 14px;
      padding: 18px 0 18px;
      border-bottom: 1px solid var(--wiki-line);
    }
    .wiki-kicker {
      margin: 0 0 8px;
      color: var(--wiki-accent);
      font-size: 12px;
      font-weight: 900;
    }
    .wiki-hero h1 {
      max-width: 880px;
      margin: 0;
      color: var(--wiki-text);
      font-size: clamp(30px, 5vw, 58px);
      line-height: 1.04;
      overflow-wrap: anywhere;
      word-break: keep-all;
    }
    .wiki-lede {
      margin: 10px 0 0;
      color: var(--wiki-secondary);
      font-size: 15px;
      font-weight: 800;
    }
    .wiki-search {
      display: grid;
      gap: 6px;
      max-width: 520px;
    }
    .wiki-search label {
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 850;
    }
    .wiki-search input {
      width: 100%;
      min-height: 44px;
      border: 1px solid var(--wiki-line);
      border-radius: 8px;
      padding: 9px 12px;
      background: var(--wiki-surface);
      color: var(--wiki-text);
      font: inherit;
      font-size: 14px;
    }
    .wiki-source-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      align-items: center;
    }
    .wiki-source-strip a,
    .wiki-source-strip span {
      min-height: 30px;
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--wiki-line);
      padding: 5px 10px;
      background: var(--wiki-surface);
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }
    .wiki-layout {
      display: grid;
      gap: 24px;
      padding-top: 16px;
    }
    .wiki-sidebar {
      display: none;
    }
    .wiki-document {
      min-width: 0;
      padding: 0;
    }
    .wiki-section {
      display: grid;
      gap: 12px;
      border-bottom: 1px solid var(--wiki-line);
      padding: 0 0 26px;
      margin-bottom: 26px;
    }
    .wiki-section:last-child {
      border-bottom: 0;
      margin-bottom: 0;
      padding-bottom: 0;
    }
    .wiki-eyebrow {
      margin: 0;
      color: var(--wiki-accent);
      font-size: 12px;
      font-weight: 900;
    }
    .wiki-section h2 {
      margin: 0;
      color: var(--wiki-text);
      font-size: clamp(22px, 3vw, 32px);
      line-height: 1.2;
      word-break: keep-all;
    }
    .wiki-section p,
    .wiki-section li,
    .wiki-section dd,
    .wiki-section td {
      margin: 0;
      color: var(--wiki-secondary);
      font-size: 15px;
      line-height: 1.75;
    }
    .wiki-source-index {
      display: grid;
      gap: 0;
      margin: 0;
      padding: 0;
      list-style: none;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-source-index li {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 54px;
      gap: 12px;
      align-items: center;
      border-bottom: 1px solid var(--wiki-line);
      padding: 11px 0;
    }
    .wiki-source-index a {
      color: var(--wiki-text);
      font-weight: 850;
      text-decoration: none;
    }
    .wiki-source-index span {
      color: var(--wiki-tertiary);
      font-size: 12px;
      font-weight: 800;
      text-align: right;
    }
    .wiki-inline-tools,
    .wiki-link-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .wiki-link-row a {
      border-bottom: 1px solid rgba(31, 107, 99, 0.4);
      color: #164c46;
      font-size: 14px;
      font-weight: 850;
      text-decoration: none;
    }
    .wiki-source-line {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      border-left: 3px solid var(--wiki-line);
      padding-left: 10px;
    }
    .wiki-source-line span {
      color: var(--wiki-tertiary);
      font-size: 12px;
      font-weight: 900;
    }
    .wiki-source-line a {
      color: #164c46;
      font-size: 13px;
      font-weight: 900;
      text-decoration: none;
    }
    .wiki-ref {
      border: 0;
      border-bottom: 1px solid rgba(31, 107, 99, 0.4);
      padding: 0 1px;
      background: transparent;
      color: #164c46;
      font: inherit;
      font-weight: 850;
      cursor: pointer;
    }
    .wiki-ref:hover { background: var(--wiki-accent-soft); }
    .wiki-definition-list {
      display: grid;
      gap: 0;
      margin: 4px 0 0;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-definition-list div {
      display: grid;
      gap: 6px;
      border-bottom: 1px solid var(--wiki-line);
      padding: 13px 0;
    }
    .wiki-definition-list dt {
      color: var(--wiki-text);
      font-size: 14px;
      font-weight: 900;
    }
    .wiki-table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-table th,
    .wiki-table td {
      border-bottom: 1px solid var(--wiki-line);
      padding: 12px 8px;
      text-align: left;
      vertical-align: top;
    }
    .wiki-table th {
      color: var(--wiki-text);
      font-size: 13px;
      font-weight: 900;
    }
    .wiki-table th:first-child,
    .wiki-table td:first-child { width: 112px; color: var(--wiki-text); font-weight: 850; }
    .wiki-timeline {
      display: grid;
      gap: 0;
      margin: 0;
      padding: 0;
      list-style: none;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-timeline li {
      display: grid;
      gap: 5px;
      border-bottom: 1px solid var(--wiki-line);
      padding: 13px 0;
    }
    .wiki-timeline strong {
      color: var(--wiki-text);
      font-size: 14px;
    }
    .wiki-reference-grid {
      display: grid;
      gap: 0;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-reference-row {
      display: grid;
      gap: 3px;
      width: 100%;
      border: 0;
      border-bottom: 1px solid var(--wiki-line);
      padding: 12px 0;
      background: transparent;
      color: var(--wiki-text);
      text-align: left;
      cursor: pointer;
    }
    .wiki-reference-row span {
      color: var(--wiki-secondary);
      font-size: 11px;
      font-weight: 850;
    }
    .wiki-reference-row strong {
      font-size: 14px;
    }
    .wiki-source-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding-left: 18px;
    }
    .wiki-source-list a {
      color: #164c46;
      font-weight: 850;
      text-decoration: none;
    }
    .wiki-section[hidden] { display: none; }
    .wiki-ref-panel {
      position: fixed;
      right: 14px;
      bottom: calc(78px + env(safe-area-inset-bottom));
      z-index: 42;
      width: min(420px, calc(100vw - 28px));
      border: 1px solid var(--wiki-line);
      border-radius: 8px;
      padding: 18px;
      background: var(--wiki-surface);
      box-shadow: 0 18px 60px rgba(15, 23, 42, 0.18);
    }
    .wiki-ref-close {
      position: absolute;
      top: 10px;
      right: 10px;
      width: 32px;
      height: 32px;
      border: 0;
      border-radius: 999px;
      background: var(--wiki-soft);
      cursor: pointer;
    }
    .wiki-ref-close::before,
    .wiki-ref-close::after {
      content: "";
      position: absolute;
      left: 9px;
      top: 15px;
      width: 14px;
      height: 2px;
      border-radius: 2px;
      background: var(--wiki-text);
    }
    .wiki-ref-close::before { transform: rotate(45deg); }
    .wiki-ref-close::after { transform: rotate(-45deg); }
    .wiki-ref-panel > span {
      display: inline-flex;
      border-radius: 999px;
      padding: 4px 8px;
      background: var(--wiki-accent-soft);
      color: #164c46;
      font-size: 11px;
      font-weight: 900;
    }
    .wiki-ref-panel h2 {
      margin: 10px 34px 8px 0;
      color: var(--wiki-text);
      font-size: 20px;
      line-height: 1.25;
    }
    .wiki-ref-panel p {
      margin: 0;
      color: var(--wiki-secondary);
      font-size: 14px;
      line-height: 1.65;
    }
    .wiki-ref-related {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 12px;
    }
    .wiki-ref-related button {
      border: 1px solid var(--wiki-line);
      border-radius: 999px;
      padding: 5px 8px;
      background: var(--wiki-soft);
      color: var(--wiki-text);
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }
    .wiki-ref-panel a {
      display: inline-flex;
      margin-top: 14px;
      color: #164c46;
      font-size: 13px;
      font-weight: 900;
      text-decoration: none;
    }
    .wiki-ref-backdrop {
      display: none;
    }
    @media (min-width: 860px) {
      .wiki-hero {
        grid-template-columns: minmax(0, 1fr) minmax(320px, 0.45fr);
        align-items: end;
      }
      .wiki-source-strip { grid-column: 1 / -1; }
      .wiki-layout {
        grid-template-columns: 260px minmax(0, 1fr);
        align-items: start;
      }
      .wiki-sidebar {
        position: sticky;
        top: 62px;
        display: grid;
        gap: 10px;
        max-height: calc(100vh - 132px);
        overflow: auto;
        padding: 8px 0;
      }
      .wiki-sidebar strong {
        color: var(--wiki-secondary);
        font-size: 12px;
        font-weight: 900;
      }
      .wiki-sidebar nav {
        display: grid;
        border-top: 1px solid var(--wiki-line);
      }
      .wiki-sidebar a {
        display: grid;
        gap: 3px;
        border-bottom: 1px solid var(--wiki-line);
        padding: 10px 0;
        color: var(--wiki-text);
        text-decoration: none;
      }
      .wiki-sidebar span {
        font-size: 13px;
        font-weight: 900;
      }
      .wiki-sidebar small {
        color: var(--wiki-secondary);
        font-size: 12px;
        line-height: 1.35;
      }
      .wiki-document { padding: 0 8px 0 0; }
      .wiki-definition-list div {
        grid-template-columns: 160px minmax(0, 1fr);
        gap: 16px;
      }
      .wiki-timeline li {
        grid-template-columns: 150px minmax(0, 1fr);
        gap: 18px;
      }
    }
    @media (max-width: 520px) {
      .wiki-shell { width: min(100% - 20px, 1220px); }
      .wiki-document { padding: 0; }
      .wiki-table th,
      .wiki-table td {
        display: block;
        width: 100% !important;
        padding: 9px 0;
      }
      .wiki-table tr {
        display: block;
        border-bottom: 1px solid var(--wiki-line);
      }
      .wiki-table th,
      .wiki-table td { border-bottom: 0; }
      .wiki-ref-panel {
        left: 10px;
        right: 10px;
        bottom: calc(72px + env(safe-area-inset-bottom));
        width: auto;
      }
    }
  </style>"""


def _page_script() -> str:
    return r"""
(() => {
  const refs = window.KPEF_WIKI_REFERENCES || {};
  const panel = document.getElementById("wikiRefPanel");
  const backdrop = document.getElementById("wikiRefBackdrop");
  const refType = document.getElementById("wikiRefType");
  const refTitle = document.getElementById("wikiRefTitle");
  const refLocation = document.getElementById("wikiRefLocation");
  const refRelated = document.getElementById("wikiRefRelated");
  const refSource = document.getElementById("wikiRefSource");
  const closeButton = panel?.querySelector(".wiki-ref-close");
  const search = document.getElementById("wikiSearch");
  const sections = Array.from(document.querySelectorAll(".wiki-section"));
  const topLinks = Array.from(document.querySelectorAll(".wiki-top-nav a"));

  const openRef = (key) => {
    const item = refs[key];
    if (!item || !panel) return;
    refType.textContent = item.type || "참조";
    refTitle.textContent = item.label || key;
    refLocation.textContent = item.location ? `위치: ${item.location}` : "";
    refSource.textContent = item.source_label ? `${item.source_label} 열기` : "공식 출처 열기";
    refSource.href = item.source_url || "#";
    refRelated.replaceChildren();
    (item.related || []).forEach((relatedKey) => {
      if (!refs[relatedKey]) return;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = refs[relatedKey].label || relatedKey;
      button.addEventListener("click", () => openRef(relatedKey));
      refRelated.append(button);
    });
    panel.hidden = false;
    if (backdrop) backdrop.hidden = false;
  };

  const closeRef = () => {
    if (panel) panel.hidden = true;
    if (backdrop) backdrop.hidden = true;
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-ref]");
    if (trigger) {
      openRef(trigger.dataset.ref);
      return;
    }
  });
  closeButton?.addEventListener("click", closeRef);
  backdrop?.addEventListener("click", closeRef);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeRef();
  });

  search?.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    sections.forEach((section) => {
      const haystack = `${section.dataset.search || ""} ${section.innerText || ""}`.toLowerCase();
      section.hidden = Boolean(query) && !haystack.includes(query);
    });
  });

  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    const id = visible.target.id;
    topLinks.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${id}`));
  }, { rootMargin: "-80px 0px -55% 0px", threshold: [0.1, 0.3, 0.6] });
  sections.forEach((section) => observer.observe(section));
})();
"""
