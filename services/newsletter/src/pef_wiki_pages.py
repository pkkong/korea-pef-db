#!/usr/bin/env python
"""Render static PEF Wiki pages for the newsletter site."""

from __future__ import annotations

from html import escape as html_escape


PEF_WIKI_SOURCE_TITLE = "기관전용 사모집합투자기구 실무안내, 2023.06"
PEF_WIKI_SOURCE_NOTE = (
    "이 페이지는 금융감독원/KDI/KVCA가 공개한 2023.06 "
    "「기관전용 사모집합투자기구 실무안내」 발간 자료와 첨부 PDF의 제1장 내용을 "
    "학습용으로 요약·해설한 것입니다. 원문 전체를 전재하지 않으며, 법률·감독상 판단은 "
    "최신 법령, 감독규정, 공식 안내 및 전문가 검토를 우선해야 합니다."
)
SOURCE_URLS = {
    "fss": "https://www.fss.or.kr/",
    "kdi": "https://eiec.kdi.re.kr/policy/materialView.do?num=240321",
    "kvca": "https://www.kvca.or.kr/Program/board/listbody.html?a_cd=12&a_gb=board&a_item=0&page=1&po_no=6352&sm=4_3&tm_num=3",
    "kvca_pdf": "https://www.kvca.or.kr/files/download.html?a_cd=12&a_gb=board&file=6352_1688103776.pdf&name=%EA%B8%B0%EA%B4%80%EC%A0%84%EC%9A%A9+%EC%82%AC%EB%AA%A8%EC%A7%91%ED%95%A9%ED%88%AC%EC%9E%90%EA%B8%B0%EA%B5%AC+%EC%8B%A4%EB%AC%B4%EC%95%88%EB%82%B4_230629.pdf",
}
APP_ICON_FILE = "apple-touch-icon.png"


def render_pef_wiki_page(report_date: str) -> str:
    """Return a complete pef-wiki.html document."""
    safe_date = html_escape(report_date)
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
      <p class="wiki-kicker">PEF Wiki</p>
      <h1>기관전용 사모집합투자기구 실무안내</h1>
      <p>공개 PDF의 제1장 ‘개관’을 실무자가 빠르게 훑을 수 있도록 재구성한 위키형 요약입니다. 원문 전체를 옮기지 않고, 도입 배경, 개요와 분류, 시장 현황, 연혁을 업무 관점으로 정리합니다.</p>
      <div class="wiki-meta">
        <span>기준일 {safe_date}</span>
        <span>원문 기준: {html_escape(PEF_WIKI_SOURCE_TITLE)}</span>
        <span>제1장 개관</span>
      </div>
    </header>

    <nav class="wiki-toc" aria-label="PEF Wiki 목차">
      <a href="#intro">제1장 개관</a>
      <a href="#background">도입 배경</a>
      <a href="#overview">개요 및 분류</a>
      <a href="#status">관련 현황</a>
      <a href="#history">연혁</a>
      <a href="#terms">읽기 전에 볼 용어</a>
      <a href="#next">다음 학습</a>
      <a href="#sources">출처</a>
    </nav>

    <section class="wiki-card" id="intro">
      <span class="wiki-section-label">제1장</span>
      <h2>개관: 이 장에서 잡아야 할 것</h2>
      <p>제1장은 기관전용 사모집합투자기구의 세부 설립·운용 절차에 들어가기 전, 한국 PEF 제도가 왜 도입됐고 어떻게 기관전용 사모펀드 체계로 바뀌었는지 설명하는 입문부입니다.</p>
      <div class="wiki-grid">
        <article>
          <h3>왜 생겼나</h3>
          <p>외환위기 이후 기업 구조조정과 장기 위험자본 공급 수요가 커지면서, 전문 운용자가 기관 자금을 모아 기업에 투자하는 제도적 통로가 필요해졌습니다.</p>
        </article>
        <article>
          <h3>무엇이 바뀌었나</h3>
          <p>2021년 사모펀드 제도 개편 이후에는 투자자 유형을 중심으로 일반 사모와 기관전용 사모가 구분되고, 기존 경영참여형 PEF 실무가 기관전용 체계 안으로 재정리됐습니다.</p>
        </article>
      </div>
    </section>

    <section class="wiki-card" id="background">
      <span class="wiki-section-label">제1절</span>
      <h2>사모투자전문회사(PEF) 제도 도입 배경</h2>
      <p>한국의 PEF 제도는 기업 구조개선, 모험자본 공급, 인수금융과 경영권 거래의 제도적 기반을 만들기 위해 도입됐습니다. 초기에는 구조조정과 buy-out 성격이 강했지만, 시간이 지나며 성장자본, minority 투자, 크레딧성 투자 등 운용 전략이 넓어졌습니다.</p>
      <ul class="wiki-checklist">
        <li>IMF 외환위기 이후 부실기업 구조조정과 경영 효율화 수요가 커졌습니다.</li>
        <li>은행 대출이나 상장시장만으로는 장기 위험자본 공급에 한계가 있었습니다.</li>
        <li>전문 운용자가 책임을 지고 기업가치 제고와 회수를 수행하는 투자기구가 필요했습니다.</li>
        <li>제도 도입 후 PEF는 국내 M&A와 비상장 투자시장의 핵심 참여자로 성장했습니다.</li>
      </ul>
    </section>

    <section class="wiki-card" id="overview">
      <span class="wiki-section-label">제2절</span>
      <h2>기관전용 사모집합투자기구 개요 및 분류</h2>
      <p>기관전용 사모집합투자기구는 전문성과 위험부담 능력이 있는 기관투자자를 대상으로 하는 사모펀드입니다. 실무에서는 “일반 투자자 보호 규율”보다 “전문 투자자 간 계약과 감독 보고”가 더 중요한 축이 됩니다.</p>
      <dl class="wiki-terms">
        <div>
          <dt>기관전용</dt>
          <dd>출자자 범위가 기관투자자 등으로 제한됩니다. 그래서 모집, 판매, 설명의무보다 적격성 확인과 운용보고 체계가 중요합니다.</dd>
        </div>
        <div>
          <dt>사모집합투자기구</dt>
          <dd>다수의 자금을 모아 운용하지만 공모 방식이 아니라 제한된 투자자를 대상으로 설정·설립되는 집합투자 구조입니다.</dd>
        </div>
        <div>
          <dt>업무집행사원(GP)</dt>
          <dd>펀드 운용, 투자 판단, 보고, 내부통제, 이해상충 관리를 책임지는 운용 주체입니다.</dd>
        </div>
        <div>
          <dt>유한책임사원(LP)</dt>
          <dd>출자자로서 약정액을 부담하고, 조합계약과 내부 기준에 따라 출자·사후관리·위원회 참여를 수행합니다.</dd>
        </div>
      </dl>
    </section>

    <section class="wiki-card" id="status">
      <span class="wiki-section-label">제3절</span>
      <h2>기관전용 사모집합투자기구 관련 현황</h2>
      <p>제1장의 현황 파트는 기관전용 PEF가 국내 자본시장에서 이미 의미 있는 규모로 성장했고, GP·LP·포트폴리오 기업·감독당국이 연결되는 별도 시장 인프라가 형성됐다는 점을 보여줍니다.</p>
      <div class="wiki-grid">
        <article>
          <h3>LP 관점</h3>
          <p>연기금, 공제회, 금융회사 등 기관 LP는 위탁운용사 선정, 출자 조건, 사후관리 기준을 통해 시장의 자금 배분을 좌우합니다.</p>
        </article>
        <article>
          <h3>GP 관점</h3>
          <p>운용사는 펀드 조성, 딜 소싱, 투자심의, 포트폴리오 관리, 회수까지 전 과정을 수행하며 운용역 트랙레코드와 내부통제가 중요해집니다.</p>
        </article>
        <article>
          <h3>기업 관점</h3>
          <p>투자대상 회사는 성장자금, 승계, carve-out, 구조조정, 경영권 거래 등 다양한 상황에서 PEF 자금을 활용할 수 있습니다.</p>
        </article>
        <article>
          <h3>감독 관점</h3>
          <p>비공개 시장이지만 설립, 변경, 해산, 운용 현황 관련 보고와 검사를 통해 시장 질서와 투자자 보호 장치가 유지됩니다.</p>
        </article>
      </div>
    </section>

    <section class="wiki-card" id="history">
      <span class="wiki-section-label">제4절</span>
      <h2>연혁</h2>
      <ol class="wiki-steps">
        <li><strong>2004년 전후: PEF 제도 도입</strong><span>기업 구조조정과 장기 위험자본 공급을 위한 사모투자전문회사 체계가 도입됐습니다.</span></li>
        <li><strong>2010년대: 시장 확대</strong><span>국내 GP와 기관 LP가 늘어나고 buy-out, growth, minority, 회수 거래가 동시에 커졌습니다.</span></li>
        <li><strong>2021년 10월: 사모펀드 체계 개편</strong><span>운용 목적 중심 구분보다 투자자 유형 중심 구분이 강조되면서 기관전용 사모펀드 체계가 본격화됐습니다.</span></li>
        <li><strong>2023년 6월: 실무안내 개정판 발간</strong><span>개편 후 실무자들이 설립, 운용, 변경보고, GP 등록, 특수목적 기구를 한 번에 확인할 수 있도록 안내서가 정리됐습니다.</span></li>
      </ol>
    </section>

    <section class="wiki-card" id="terms">
      <span class="wiki-section-label">용어</span>
      <h2>읽기 전에 볼 용어</h2>
      <p>제1장은 개관이지만 이후 장을 읽기 위한 핵심 용어가 계속 등장합니다. 이 페이지에서는 원문을 처음 읽는 독자가 막히지 않도록 최소 용어만 정리합니다.</p>
      <dl class="wiki-terms">
        <div>
          <dt>출자약정</dt>
          <dd>LP가 펀드에 출자하기로 약속한 총액입니다. 실제 납입은 투자 집행 일정에 따라 순차적으로 이뤄질 수 있습니다.</dd>
        </div>
        <div>
          <dt>설립·변경·해산 보고</dt>
          <dd>펀드의 주요 상태 변화가 있을 때 감독당국에 제출하는 보고 축입니다. 기한과 제출 항목을 운영 프로세스에 넣어야 합니다.</dd>
        </div>
        <div>
          <dt>특수목적 기구</dt>
          <dd>기업재무안정, 창업·벤처전문 등 특정 정책 목적이나 투자 목적을 가진 기관전용 사모펀드 유형을 말합니다.</dd>
        </div>
      </dl>
    </section>

    <section class="wiki-card" id="next">
      <span class="wiki-section-label">다음</span>
      <h2>다음 학습 경로</h2>
      <div class="wiki-path">
        <a href="#background">1. 제도 도입 이유</a>
        <a href="#overview">2. 기관전용 구조</a>
        <a href="#status">3. LP/GP 시장 현황</a>
        <a href="#history">4. 제도 변화</a>
      </div>
      <p class="wiki-note">다음 페이지로 확장할 때는 제2장의 설립·보고·운용 절차, 제3장의 GP 등록 제도, 제5장의 FAQ를 각각 별도 문서로 나누는 구조가 좋습니다.</p>
    </section>

    <section class="wiki-card wiki-source-card" id="sources">
      <span class="wiki-section-label">출처</span>
      <h2>출처와 이용 범위</h2>
      <p>{html_escape(PEF_WIKI_SOURCE_NOTE)}</p>
      <ul>
        <li><a href="{html_escape(SOURCE_URLS["kdi"])}" target="_blank" rel="noreferrer">KDI 경제정보센터 정책자료</a></li>
        <li><a href="{html_escape(SOURCE_URLS["kvca"])}" target="_blank" rel="noreferrer">KVCA 일반자료실 게시글</a></li>
        <li><a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">KVCA 첨부 PDF</a></li>
        <li><a href="{html_escape(SOURCE_URLS["fss"])}" target="_blank" rel="noreferrer">금융감독원 홈페이지</a></li>
      </ul>
    </section>
  </main>
  {_render_bottom_nav()}
</body>
</html>
"""


def _app_head_meta() -> str:
    return f"""  <meta name="theme-color" content="#111827">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="KPEF Wiki">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <link rel="apple-touch-icon" href="{APP_ICON_FILE}">
  <link rel="icon" type="image/png" href="{APP_ICON_FILE}">
  <link rel="manifest" href="site.webmanifest">"""


def _render_top_nav() -> str:
    return """    <nav class="wiki-top-nav" aria-label="서비스 메뉴">
      <strong>Korea PEF Intelligence</strong>
      <span>
        <a href="index.html">브리프</a>
        <a href="lp-notices.html">LP</a>
        <a href="gps.html">GP</a>
        <a class="active" href="pef-wiki.html">PEF Wiki</a>
      </span>
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
      --wiki-bg: #f5f7f8;
      --wiki-surface: #ffffff;
      --wiki-muted: #eef3f5;
      --wiki-text: #17202a;
      --wiki-secondary: #52616f;
      --wiki-line: #dce4e8;
      --wiki-accent: #1f6b63;
      --wiki-accent-soft: #e7f4f1;
      --wiki-warm: #8b6f2a;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background: var(--wiki-bg);
      color: var(--wiki-text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    a { color: inherit; }
    .wiki-shell {
      width: min(1120px, calc(100% - 28px));
      margin: 0 auto;
      padding: 16px 0 calc(98px + env(safe-area-inset-bottom));
    }
    .wiki-top-nav {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      padding: 8px 0;
      background: rgba(245, 247, 248, 0.94);
      backdrop-filter: blur(14px);
    }
    .wiki-top-nav strong { font-size: 13px; }
    .wiki-top-nav span { display: flex; flex-wrap: wrap; gap: 7px; }
    .wiki-top-nav a {
      display: inline-flex;
      min-height: 34px;
      align-items: center;
      border: 1px solid var(--wiki-line);
      border-radius: 8px;
      padding: 7px 11px;
      background: var(--wiki-surface);
      color: var(--wiki-text);
      font-size: 12px;
      font-weight: 750;
      text-decoration: none;
    }
    .wiki-top-nav a.active {
      border-color: var(--wiki-accent);
      background: var(--wiki-accent-soft);
      color: #164c46;
    }
    .wiki-hero {
      display: grid;
      gap: 10px;
      margin: 14px 0;
      padding: 22px 0 10px;
      border-bottom: 1px solid var(--wiki-line);
    }
    .wiki-kicker,
    .wiki-section-label {
      width: fit-content;
      border-left: 3px solid var(--wiki-accent);
      padding-left: 8px;
      color: #164c46;
      font-size: 12px;
      font-weight: 850;
    }
    .wiki-hero h1 {
      max-width: 850px;
      margin: 0;
      font-size: clamp(30px, 5vw, 54px);
      line-height: 1.05;
      letter-spacing: 0;
      overflow-wrap: anywhere;
      word-break: keep-all;
    }
    .wiki-hero p {
      max-width: 760px;
      margin: 0;
      color: var(--wiki-secondary);
      font-size: 16px;
      line-height: 1.65;
    }
    .wiki-meta { display: flex; flex-wrap: wrap; gap: 8px; }
    .wiki-meta span {
      border: 1px solid var(--wiki-line);
      border-radius: 999px;
      padding: 6px 10px;
      background: var(--wiki-surface);
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 750;
    }
    .wiki-toc {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      margin: 0 0 12px;
      padding: 2px 0 8px;
    }
    .wiki-toc a,
    .wiki-path a {
      flex: 0 0 auto;
      border: 1px solid var(--wiki-line);
      border-radius: 999px;
      padding: 8px 11px;
      background: var(--wiki-surface);
      color: var(--wiki-text);
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }
    .wiki-card {
      display: grid;
      gap: 12px;
      margin: 10px 0;
      border: 1px solid var(--wiki-line);
      border-radius: 8px;
      padding: 18px;
      background: var(--wiki-surface);
    }
    .wiki-card h2,
    .wiki-card h3,
    .wiki-card p { margin: 0; }
    .wiki-card h2 { font-size: 22px; line-height: 1.25; }
    .wiki-card h3 { font-size: 15px; }
    .wiki-card p,
    .wiki-card li,
    .wiki-card dd {
      color: var(--wiki-secondary);
      font-size: 14px;
      line-height: 1.7;
    }
    .wiki-grid,
    .wiki-participants {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .wiki-grid article,
    .wiki-participants article {
      border: 1px solid var(--wiki-line);
      border-radius: 8px;
      padding: 14px;
      background: var(--wiki-muted);
    }
    .wiki-terms {
      display: grid;
      gap: 8px;
      margin: 0;
    }
    .wiki-terms div {
      display: grid;
      grid-template-columns: minmax(150px, 0.34fr) 1fr;
      gap: 10px;
      border-top: 1px solid var(--wiki-line);
      padding-top: 9px;
    }
    .wiki-terms dt { font-size: 13px; font-weight: 850; }
    .wiki-terms dd { margin: 0; }
    .wiki-steps,
    .wiki-checklist {
      display: grid;
      gap: 9px;
      margin: 0;
      padding-left: 20px;
    }
    .wiki-steps li strong { display: block; color: var(--wiki-text); font-size: 14px; }
    .wiki-steps li span { display: block; color: var(--wiki-secondary); }
    .wiki-path { display: flex; flex-wrap: wrap; gap: 8px; }
    .wiki-note {
      border-left: 3px solid var(--wiki-warm);
      padding-left: 10px;
    }
    .wiki-source-card ul {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .wiki-source-card li a {
      display: inline-flex;
      border: 1px solid var(--wiki-line);
      border-radius: 8px;
      padding: 8px 10px;
      background: var(--wiki-muted);
      color: var(--wiki-text);
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }
    @media (max-width: 760px) {
      .wiki-top-nav { align-items: start; flex-direction: column; }
      .wiki-top-nav span { flex-wrap: nowrap; width: 100%; overflow-x: auto; padding-bottom: 3px; }
      .wiki-top-nav a { flex: 0 0 auto; }
      .wiki-grid,
      .wiki-participants,
      .wiki-terms div { grid-template-columns: 1fr; }
      .wiki-card { padding: 15px; }
    }
  </style>"""
