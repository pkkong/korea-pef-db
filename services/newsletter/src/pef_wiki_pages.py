#!/usr/bin/env python
"""Render static PEF Wiki pages for the newsletter site."""

from __future__ import annotations
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

CHAPTER_SECTIONS = [
    ("chapter", "문서 개요", "관리 정보"),
    ("background", "제도의 의의 및 도입 배경", "의의·경과"),
    ("reform", "사모펀드 체계 개편", "분류·투자자"),
    ("operations", "자산운용 규제", "운용 자율성"),
    ("actors", "주요 주체 및 용어", "GP·LP"),
    ("market", "관련 현황", "시장 규모"),
    ("history", "연혁", "제도 변화"),
    ("sources", "문서 기준", "기준 자료"),
]


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
    <header class="wiki-doc-header">
      <div>
        <p class="wiki-kicker">PEF Wiki · 제1장</p>
        <h1>기관전용 사모집합투자기구 실무안내</h1>
        <p class="wiki-lede">개관</p>
      </div>
      <form class="wiki-search" role="search">
        <label for="wikiSearch">문서 검색</label>
        <input id="wikiSearch" type="search" placeholder="예: GP, LP, 자본시장법, 보고">
        <p class="wiki-search-status" id="wikiSearchStatus" aria-live="polite"></p>
      </form>
      <div class="wiki-doc-meta" aria-label="문서 기준">
        <span>금융감독원 실무안내</span>
        <span>제1장 개관 본문</span>
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

      <article class="wiki-document" aria-label="기관전용 사모집합투자기구 실무안내 제1장 본문">
        {_render_wiki_article()}
      </article>
    </div>
  </main>
  {_render_bottom_nav()}
  <script>{_page_script()}</script>
</body>
</html>
"""


def _render_wiki_article() -> str:
    return f"""
        <section class="wiki-section" id="chapter" data-search="문서 개요 기관전용 사모집합투자기구 실무안내 사내 위키 컴플라이언스 GP 운용 가이드">
          <p class="wiki-eyebrow">사내 위키</p>
          <h2>제1장 기관전용 사모집합투자기구 개요</h2>
          <dl class="wiki-meta-list" aria-label="문서 관리">
            <div><dt>문서 분류</dt><dd>컴플라이언스 / GP 운용 가이드</dd></div>
            <div><dt>관련 법령</dt><dd><a class="wiki-inline-link" href="#term-capital_markets_act">자본시장과 금융투자업에 관한 법률</a></dd></div>
            <div><dt>원문 출처</dt><dd>금융감독원 자산운용감독국 「기관전용 사모집합투자기구 실무안내」</dd></div>
          </dl>
          <ul class="wiki-bullet-list">
            <li>이 장은 기관전용 사모집합투자기구의 의의, 도입 배경, 제도 개편, 운용규제, 주요 주체, 시장 현황과 연혁을 다룹니다.</li>
          </ul>
        </section>

        <section class="wiki-section" id="background" data-search="제도의 의의 도입 배경 외환위기 기업 구조조정 위험자본 모험자본 buyout m&a pef">
          <p class="wiki-eyebrow">1</p>
          <h2>제도의 의의 및 도입 배경</h2>
          <div class="wiki-subsection">
            <h3>제도의 의의</h3>
            <ul class="wiki-bullet-list">
              <li><strong>기관전용 사모집합투자기구</strong>는 전문성과 위험관리능력을 갖춘 기관투자자 및 이에 준하는 자로부터만 출자를 받아 운용하는 사모집합투자기구입니다.</li>
              <li><a class="wiki-inline-link" href="#term-gp">업무집행사원(GP)</a>이 설립과 운용을 주도하고, 기업의 지분 등에 투자해 경영권 참여, 구조조정, 성장자본 공급 등을 수행합니다.</li>
              <li>투자 후 기업가치를 높이고 그 수익을 사원에게 배분한다는 점에서 국내 모험자본 공급 체계의 핵심 수단으로 기능합니다.</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>도입 배경 및 추진 경과</h3>
            <ul class="wiki-bullet-list">
              <li>외환위기 이후 비효율적 지배구조와 취약한 경영능력을 가진 기업에 대한 구조조정 수요가 커졌습니다.</li>
              <li>외국계 사모펀드가 국내 금융기관과 기업 인수·매각에서 적극적으로 움직이면서 국내 장기 위험자본 육성 필요성이 부각됐습니다.</li>
              <li>기존 구조조정 제도는 목적과 투자대상이 좁아 자금조성, 투자, 경영개선, 회수를 한 번에 수행하는 데 한계가 있었습니다.</li>
              <li>2004년 사모투자전문회사 제도가 도입되면서 기관투자자 자금을 기업 인수와 경영개선에 연결하는 제도적 기반이 마련됐습니다.</li>
              <li>2021년 10월 사모펀드 체계개편으로 기존 경영참여형 사모펀드는 기관전용 사모집합투자기구 체계로 재편됐습니다.</li>
            </ul>
          </div>
        </section>

        <section class="wiki-section" id="reform" data-search="사모펀드 체계 개편 일반 사모 기관전용 사모 투자자 범위 위험감수능력 전문투자형 경영참여형 49인 100인">
          <p class="wiki-eyebrow">2</p>
          <h2>사모펀드 체계 개편의 주요 내용</h2>
          <div class="wiki-subsection">
            <h3>분류체계 일원화</h3>
            <p class="wiki-paragraph">사모펀드를 운용목적에 따라 구분하던 방식에서 투자자의 위험감수능력과 전문성을 기준으로 구분하는 방식으로 개편했습니다.</p>
            <ul class="wiki-bullet-list">
              <li><strong>개정 전</strong>: 전문투자형 사모펀드 / 경영참여형 사모펀드</li>
              <li><strong>개정 후</strong>: 일반 사모집합투자기구 / 기관전용 사모집합투자기구</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>투자자(LP) 범위의 제한</h3>
            <ul class="wiki-bullet-list">
              <li>기관전용 사모펀드는 법령상 기관투자자 등으로 인정되는 자만 <a class="wiki-inline-link" href="#term-lp">유한책임사원(LP)</a>으로 참여할 수 있습니다.</li>
              <li>국가, 한국은행, 금융기관, 연기금, 공공기관, 이에 준하는 특수법인 등이 주요 투자자 범위에 포함됩니다.</li>
              <li>일반 개인투자자의 참여는 원칙적으로 제한됩니다. 다만 해당 펀드를 운용하는 업무집행사원(GP)의 임원 또는 운용전문인력 등은 예외적으로 참여할 수 있습니다.</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>투자자 수 제한 확대</h3>
            <p class="wiki-paragraph">사모펀드의 투자자 수 기준은 종전 49인 이하에서 100인 이하로 확대되었습니다. 기관전용 사모펀드는 일반 개인투자자가 유입되지 않는 구조를 전제로 하므로, 기관투자자 간 펀드 결성의 자율성이 확대됐습니다.</p>
          </div>
          <div class="wiki-subsection">
            <h3>기관전용 사모집합투자기구의 유형</h3>
            <p class="wiki-paragraph">기관전용 사모집합투자기구는 일반 기관전용 사모펀드를 기본으로 하며, 기업재무안정, 창업·벤처, 기업구조개선, 해외자원개발, 해외농업·산림자원개발, 해외건설 등 특수 목적형 제도가 별도 법률에 따라 운용됩니다.</p>
          </div>
        </section>

        <section class="wiki-section" id="operations" data-search="자산운용 규제 완화 경영참여 10% 지분보유 금전대여 대출 차입 레버리지 채무보증 400%">
          <p class="wiki-eyebrow">3</p>
          <h2>자산운용 규제 완화 및 일원화</h2>
          <div class="wiki-subsection">
            <h3>경영참여 의무 폐지</h3>
            <p class="wiki-paragraph">기존 경영참여형 PEF에 적용되던 대표적인 칸막이 규제는 사모펀드 체계개편 과정에서 폐지 또는 완화되었습니다.</p>
            <ul class="wiki-bullet-list">
              <li>투자 후 일정 기간 내 10% 이상 지분을 확보해야 하는 의무가 폐지됐습니다.</li>
              <li>일정 기간 이상 지분을 보유해야 하는 의무와 의결권 없는 주식에 대한 투자 제한도 완화됐습니다.</li>
              <li>기관전용 사모펀드는 소수 지분, 메자닌, 성장자본 등 투자대상 기업의 상황에 맞는 전략을 사용할 수 있습니다.</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>금전대여 운용 허용</h3>
            <p class="wiki-paragraph">기관전용 사모펀드는 자산운용 방법의 하나로 기업에 대한 금전대여를 활용할 수 있습니다. 다만 개인대출과 사행성 업종 관련 대출 등은 제한됩니다.</p>
          </div>
          <div class="wiki-subsection">
            <h3>차입 및 채무보증 한도</h3>
            <p class="wiki-paragraph">차입과 채무보증 한도는 펀드와 투자목적회사를 합산해 순자산의 400% 이내로 관리됩니다. 이 기준은 구조화 투자와 인수금융을 사용할 때 중요한 운용 한도입니다.</p>
          </div>
        </section>

        <section class="wiki-section" id="actors" data-search="주요 주체 핵심 용어 gp lp 업무집행사원 유한책임사원 spc 투자목적회사 자금모집 투자 기업가치 회수">
          <p class="wiki-eyebrow">4</p>
          <h2>주요 주체 및 핵심 용어 정의</h2>
          <div class="wiki-definition-block" id="term-gp">
            <h3>업무집행사원(GP, General Partner)</h3>
            <p>무한책임을 지며 기관전용 사모펀드를 설립하고 그 재산을 운용·관리하며 업무를 집행하는 사원입니다. 자본시장법상 등록이 필요합니다.</p>
          </div>
          <div class="wiki-definition-block" id="term-lp">
            <h3>유한책임사원(LP, Limited Partner)</h3>
            <p>출자 가액을 한도로 책임을 부담하는 사원입니다. 기관전용 사모펀드에서는 자본시장법령이 정하는 기관투자자 등이 LP로 참여합니다.</p>
          </div>
          <div class="wiki-definition-block" id="term-spc">
            <h3>투자목적회사(SPC)</h3>
            <p>특정 투자대상에 대한 인수·투자 구조를 담기 위해 설립되는 중간 기구입니다. 펀드와 투자대상회사 사이에서 거래 구조를 구성할 때 활용됩니다.</p>
          </div>
          <div class="wiki-definition-block" id="term-capital_markets_act">
            <h3>자본시장법</h3>
            <p>기관전용 사모집합투자기구의 정의, 투자자 범위, 업무집행사원 등록, 운용과 보고 체계의 기본 근거가 되는 법률입니다.</p>
          </div>
          <div class="wiki-subsection">
            <h3>투자 업무 흐름</h3>
            <ol class="wiki-body-list">
              <li id="term-fund_raising"><strong>자금모집</strong>: GP가 전문성과 위험감수능력을 갖춘 투자자에게 출자를 제안하고 출자약정을 확보합니다.</li>
              <li id="term-investment"><strong>투자</strong>: 투자대상기업 발굴, 실사, 투자 타당성 검토, 거래구조 설계와 투자 집행이 이루어집니다.</li>
              <li id="term-value_addition"><strong>기업가치 제고</strong>: 임원 파견, 경영·재무 자문, 사업구조 또는 지배구조 개선으로 기업가치를 높입니다.</li>
              <li id="term-exit"><strong>매각·회수</strong>: 지분 매각, 전략적 투자자 매각, 재무적 투자자 매각, 상장 등을 통해 투자자본을 회수합니다.</li>
            </ol>
          </div>
        </section>

        <section class="wiki-section" id="market" data-search="관련 현황 시장 규모 펀드 수 약정액 이행액 gp 전문운용사 2022년 1098 125.3조 97.1조 415">
          <p class="wiki-eyebrow">5</p>
          <h2>관련 현황</h2>
          <p class="wiki-paragraph">2022년 12월말 기준 기관전용 사모집합투자기구는 1,098개, 약정액은 125.3조원, 이행액은 97.1조원입니다. 업무집행사원은 총 415사이며, 이 중 전문운용사는 312사로 전체 업무집행사원의 75.2%입니다.</p>
          <dl class="wiki-meta-list wiki-stat-list" aria-label="시장 규모">
            <div><dt>펀드 수</dt><dd>2004년말 2개에서 2022년말 1,098개로 증가</dd></div>
            <div><dt>약정액</dt><dd>0.4조원에서 125.3조원으로 증가</dd></div>
            <div><dt>이행액</dt><dd>0.3조원에서 97.1조원으로 증가</dd></div>
            <div><dt>GP 현황</dt><dd>총 415사 중 전문운용사 312사, 금융회사 46사, 창투계 회사 57사</dd></div>
          </dl>
          <p class="wiki-source-note">기준: 금융감독원 「기관전용 사모집합투자기구 실무안내」, 2022년 12월말 현황.</p>
        </section>

        <section class="wiki-section" id="history" data-search="연혁 2004 2006 2007 2009 2010 2013 2015 2021 사모펀드 제도 개편">
          <p class="wiki-eyebrow">6</p>
          <h2>연혁</h2>
          <ol class="wiki-timeline">
            <li><strong>2004년</strong><span>간접투자자산 운용업법에 합자회사 형태의 사모투자전문회사 제도가 도입되며 국내 PEF 제도가 출발했습니다.</span></li>
            <li><strong>2006년</strong><span>시행령 개정으로 유한책임사원 최소 출자가액 완화, 자산운용 범위 확대, 의무투자비율 완화가 이루어졌습니다.</span></li>
            <li><strong>2007년</strong><span>해외 회사 또는 SPC를 통한 해외자산 투자와 해외 부실채권 투자가 허용되어 투자대상이 확장되었습니다.</span></li>
            <li><strong>2009년</strong><span>자본시장법 체계로 전환되며 투자목적회사 범위, 등록 공고, 여유자금 운용, 대기업집단 관련 규제가 정비되었습니다.</span></li>
            <li><strong>2010년</strong><span>기업재무안정 PEF가 도입되어 재무구조개선기업 등에 대한 민간 자금 공급 통로가 마련되었습니다.</span></li>
            <li><strong>2013년</strong><span>GP 등록제, 보고의무, 유한책임사원의 운용 관여 제한이 명확해지며 운용사 관리와 LP-GP 역할 구분이 강화되었습니다.</span></li>
            <li><strong>2015년</strong><span>적격투자자 범위, 업무집행사원 감독, 설립규제, 금융전업그룹 규제가 정비되어 사모펀드 시장 확대와 감독체계 정비가 함께 진행되었습니다.</span></li>
            <li><strong>2021년</strong><span>전문투자형·경영참여형 구분이 일반 사모·기관전용 사모 체계로 재편되며 기관전용 사모펀드의 운용범위 확대와 투자자 보호 강화가 이루어졌습니다.</span></li>
          </ol>
        </section>

        <section class="wiki-section" id="sources" data-search="문서 기준 kvca kdi 금융감독원 실무안내 국가법령정보센터">
          <p class="wiki-eyebrow">문서 기준</p>
          <h2>문서 기준</h2>
          <p class="wiki-paragraph">기준 문서: 「기관전용 사모집합투자기구 실무안내」 제1장 개관.</p>
          <ul class="wiki-source-list">
            <li><a href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">기관전용 사모집합투자기구 실무안내 전문</a></li>
            <li><a href="{html_escape(SOURCE_URLS["kvca"])}" target="_blank" rel="noreferrer">KVCA 일반자료실 게시글</a></li>
            <li><a href="{html_escape(SOURCE_URLS["kdi"])}" target="_blank" rel="noreferrer">KDI 경제정보센터 정책자료</a></li>
            <li><a href="{html_escape(SOURCE_URLS["fss"])}" target="_blank" rel="noreferrer">금융감독원</a></li>
            <li><a href="{html_escape(SOURCE_URLS["law"])}" target="_blank" rel="noreferrer">국가법령정보센터</a></li>
          </ul>
        </section>
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
    return """    <nav class="wiki-service-nav" aria-label="서비스 이동">
      <a href="index.html">브리프</a>
      <a href="lp-notices.html">LP</a>
      <a href="gps.html">GP</a>
      <a class="active" href="pef-wiki.html">Wiki</a>
      <a href="index.html#saved">저장</a>
    </nav>
    <nav class="wiki-top-nav" aria-label="Wiki 내부 이동">
      <a class="active" href="#chapter">개요</a>
      <a href="#background">도입 배경</a>
      <a href="#reform">체계 개편</a>
      <a href="#operations">운용 규제</a>
      <a href="#actors">주체·용어</a>
      <a href="#market">현황</a>
      <a href="#history">연혁</a>
      <a href="#sources">문서 기준</a>
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
      --wiki-bg: #ffffff;
      --wiki-surface: #ffffff;
      --wiki-soft: #f6f8f9;
      --wiki-text: #17202a;
      --wiki-secondary: #52616f;
      --wiki-tertiary: #7a8793;
      --wiki-line: #e7edf1;
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
    .wiki-inline-link {
      border-bottom: 1px solid rgba(31, 107, 99, 0.4);
      color: #164c46;
      font-weight: 850;
      text-decoration: none;
    }
    .wiki-inline-link:hover {
      background: var(--wiki-accent-soft);
    }
    .wiki-shell {
      width: min(1180px, calc(100% - 28px));
      margin: 0 auto;
      padding: 12px 0 calc(106px + env(safe-area-inset-bottom));
    }
    .wiki-service-nav {
      display: none;
      gap: 18px;
      align-items: center;
      min-height: 38px;
      color: var(--wiki-secondary);
      font-size: 13px;
      font-weight: 850;
    }
    .wiki-service-nav a {
      color: inherit;
      text-decoration: none;
    }
    .wiki-service-nav a.active {
      color: var(--wiki-text);
    }
    .wiki-top-nav {
      position: sticky;
      top: 0;
      z-index: 24;
      display: flex;
      gap: 16px;
      overflow-x: auto;
      padding: 7px 0 9px;
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(14px);
    }
    .wiki-top-nav a {
      flex: 0 0 auto;
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      border-bottom: 2px solid transparent;
      padding: 7px 0;
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 800;
      text-decoration: none;
    }
    .wiki-top-nav a.active {
      border-color: var(--wiki-accent);
      color: #164c46;
    }
    .wiki-doc-header {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 14px;
      padding: 18px 0 14px;
    }
    .wiki-kicker {
      margin: 0 0 8px;
      color: var(--wiki-accent);
      font-size: 12px;
      font-weight: 900;
    }
    .wiki-doc-header h1 {
      max-width: 880px;
      margin: 0;
      color: var(--wiki-text);
      font-size: clamp(25px, 3vw, 34px);
      line-height: 1.18;
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
    .wiki-search-status {
      min-height: 18px;
      margin: 0;
      color: var(--wiki-tertiary);
      font-size: 12px;
      font-weight: 800;
    }
    .wiki-doc-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 850;
    }
    .wiki-doc-meta span {
      display: inline-flex;
      align-items: center;
      min-height: 0;
      padding: 0;
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
      padding: 0;
      margin-bottom: 42px;
    }
    .wiki-section:last-child {
      margin-bottom: 0;
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
    .wiki-section h3 {
      margin: 0;
      color: var(--wiki-text);
      font-size: 18px;
      line-height: 1.35;
      word-break: keep-all;
    }
    .wiki-section p,
    .wiki-section li,
    .wiki-section dd {
      margin: 0;
      color: var(--wiki-secondary);
      font-size: 14px;
      line-height: 1.65;
    }
    .wiki-paragraph {
      max-width: 880px;
    }
    .wiki-subsection {
      display: grid;
      gap: 10px;
      padding: 2px 0;
    }
    .wiki-body-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding-left: 18px;
    }
    .wiki-bullet-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding-left: 18px;
    }
    .wiki-bullet-list strong {
      color: var(--wiki-text);
      font-weight: 900;
    }
    .wiki-meta-list {
      display: grid;
      gap: 8px;
      margin: 2px 0 0;
    }
    .wiki-meta-list div {
      display: grid;
      gap: 5px;
      padding: 3px 0;
    }
    .wiki-meta-list dt {
      color: var(--wiki-text);
      font-size: 13px;
      font-weight: 900;
    }
    .wiki-meta-list dd {
      margin: 0;
    }
    .wiki-stat-list dd {
      color: var(--wiki-text);
      font-weight: 780;
    }
    .wiki-definition-block {
      display: grid;
      gap: 7px;
      padding: 7px 0 4px;
    }
    .wiki-definition-block p {
      max-width: 860px;
    }
    .wiki-stat-strip {
      display: grid;
      gap: 10px;
    }
    .wiki-stat-strip div {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 2px 0;
    }
    .wiki-stat-strip span {
      color: var(--wiki-secondary);
      font-size: 13px;
      font-weight: 850;
    }
    .wiki-stat-strip strong {
      color: var(--wiki-text);
      font-size: 22px;
      line-height: 1.2;
      white-space: nowrap;
    }
    .wiki-source-index {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .wiki-source-index li {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 66px;
      gap: 12px;
      align-items: center;
      padding: 3px 0;
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
      white-space: nowrap;
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
    .wiki-source-note {
      margin: 0;
      color: var(--wiki-tertiary);
      font-size: 12px;
      font-weight: 780;
      line-height: 1.55;
    }
    .wiki-definition-list {
      display: grid;
      gap: 8px;
      margin: 4px 0 0;
    }
    .wiki-definition-list div {
      display: grid;
      gap: 6px;
      padding: 3px 0;
    }
    .wiki-definition-list dt {
      color: var(--wiki-text);
      font-size: 14px;
      font-weight: 900;
    }
    .wiki-timeline,
    .wiki-event-list {
      display: grid;
      gap: 0;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .wiki-timeline li,
    .wiki-event-list li {
      display: grid;
      gap: 5px;
      padding: 7px 0;
    }
    .wiki-timeline strong,
    .wiki-event-list strong {
      color: var(--wiki-text);
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
    .bottom-nav.newsletter-only {
      background: rgba(255, 255, 255, 0.98);
      box-shadow: 0 -10px 30px rgba(15, 23, 42, 0.08);
    }
    @media (min-width: 860px) {
      .wiki-service-nav { display: flex; }
      .wiki-doc-header {
        grid-template-columns: minmax(0, 1fr) minmax(320px, 0.45fr);
        align-items: start;
      }
      .wiki-doc-meta { grid-column: 1 / -1; }
      .wiki-layout {
        grid-template-columns: 260px minmax(0, 1fr);
        align-items: start;
      }
      .wiki-sidebar {
        position: sticky;
        top: 86px;
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
        gap: 12px;
      }
      .wiki-sidebar a {
        display: grid;
        gap: 3px;
        padding: 0;
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
      .bottom-nav.newsletter-only { display: none; }
      .wiki-definition-list div {
        grid-template-columns: 160px minmax(0, 1fr);
        gap: 16px;
      }
      .wiki-meta-list div {
        grid-template-columns: 160px minmax(0, 1fr);
        gap: 16px;
      }
      .wiki-timeline li,
      .wiki-event-list li {
        grid-template-columns: 150px minmax(0, 1fr);
        gap: 18px;
      }
    }
    @media (max-width: 520px) {
      .wiki-shell { width: min(100% - 20px, 1220px); }
      .wiki-document { padding: 0; }
      .wiki-subsection { overflow-x: auto; }
    }
  </style>"""


def _page_script() -> str:
    return r"""
(() => {
  const search = document.getElementById("wikiSearch");
  const searchStatus = document.getElementById("wikiSearchStatus");
  const sections = Array.from(document.querySelectorAll(".wiki-section"));
  const topLinks = Array.from(document.querySelectorAll(".wiki-top-nav a"));

  search?.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    let matchCount = 0;
    sections.forEach((section) => {
      const haystack = `${section.dataset.search || ""} ${section.innerText || ""}`.toLowerCase();
      const matched = !query || haystack.includes(query);
      section.hidden = !matched;
      if (query && matched) matchCount += 1;
    });
    if (searchStatus) {
      searchStatus.textContent = query ? `${matchCount}개 섹션 표시` : "";
    }
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
