#!/usr/bin/env python
"""Render static PEF Wiki pages for the newsletter site."""

from __future__ import annotations
from html import escape as html_escape


PEF_WIKI_SOURCE_TITLE = "기관전용 사모집합투자기구 실무안내, 2023.06"
SOURCE_URLS = {
    "fss": "https://www.fss.or.kr/",
    "law": "https://www.law.go.kr/",
    "law_capital_markets_act": "https://law.go.kr/LSW/lsInfoP.do?lsiSeq=277365",
    "nts": "https://www.nts.go.kr/",
    "tax_law": "https://taxlaw.nts.go.kr/",
    "hometax": "https://www.hometax.go.kr/",
    "kdi": "https://eiec.kdi.re.kr/policy/materialView.do?num=240321",
    "kvca": "https://www.kvca.or.kr/Program/board/listbody.html?a_cd=12&a_gb=board&a_item=0&page=1&po_no=6352&sm=4_3&tm_num=3",
    "kvca_guide_file": "https://www.kvca.or.kr/files/download.html?a_cd=12&a_gb=board&file=6352_1688103776.pdf&name=%EA%B8%B0%EA%B4%80%EC%A0%84%EC%9A%A9+%EC%82%AC%EB%AA%A8%EC%A7%91%ED%95%A9%ED%88%AC%EC%9E%90%EA%B8%B0%EA%B5%AC+%EC%8B%A4%EB%AC%B4%EC%95%88%EB%82%B4_230629.pdf",
}
APP_ICON_FILE = "apple-touch-icon.png"

WIKI_SECTIONS = [
    ("chapter", "제1장 개요", "실무안내 본문"),
    ("meaning", "제도의 의의", "정의·기능"),
    ("background", "도입 배경", "구조조정·위험자본"),
    ("reform", "사모펀드 체계 개편", "분류·제도"),
    ("investors", "투자자 범위", "LP 적격성"),
    ("operations", "자산운용 규제", "운용 자율성"),
    ("actors", "주요 주체 및 용어", "GP·LP"),
    ("market", "관련 현황", "시장 규모"),
    ("history", "연혁", "제도 변화"),
    ("law-map", "관련 법률·규정", "조문·시행일"),
    ("tax-filings", "세무신고", "신고·납부 원천"),
    ("fss-reporting", "금감원 보고", "보고 이벤트"),
    ("practice-checklists", "실무 체크리스트", "설립·운용·회수"),
    ("sources", "공식 출처", "원천 링크"),
]


def render_pef_wiki_page(report_date: str) -> str:
    """Return a complete pef-wiki.html document."""
    safe_date = html_escape(report_date)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>PEF Wiki - 기관전용 사모집합투자기구 실무 지식베이스</title>
{_app_head_meta()}
  <link rel="stylesheet" href="assets/service.css">
  {_page_styles()}
</head>
<body>
  <main class="wiki-shell">
    {_render_top_nav()}
    {_render_mobile_drawer()}
    <header class="wiki-doc-header">
      <div>
        <p class="wiki-kicker">PEF Wiki</p>
        <h1>기관전용 사모집합투자기구</h1>
        <p class="wiki-lede">실무안내 제1장 개관을 시작으로 제도 개요, 관련 법령, 보고, 세무, 체크리스트를 문서 단위로 연결합니다.</p>
      </div>
      <form class="wiki-search" role="search">
        <label for="wikiSearch">문서 검색</label>
        <input id="wikiSearch" type="search" placeholder="예: GP, 세무, 설립 보고, 자본시장법">
        <p class="wiki-search-status" id="wikiSearchStatus" aria-live="polite"></p>
      </form>
      <div class="wiki-doc-meta" aria-label="문서 기준">
        <span>원문: {html_escape(PEF_WIKI_SOURCE_TITLE)}</span>
        <span>기준일 {safe_date}</span>
      </div>
    </header>

    <div class="wiki-layout">
      <aside class="wiki-sidebar" id="wiki-nav" aria-label="문서 목차">
        <strong>문서 목차</strong>
        <nav>
{_render_sidebar_links()}
        </nav>
      </aside>

      <article class="wiki-document" aria-label="기관전용 사모집합투자기구 실무 지식베이스">
        {_render_wiki_article()}
      </article>
    </div>
  </main>
  <script>{_page_script()}</script>
</body>
</html>
"""


def _render_wiki_article() -> str:
    return f"""
        <section class="wiki-section" id="chapter" data-search="문서 개요 기관전용 사모집합투자기구 실무안내 법령 보고 세무 체크리스트">
          <p class="wiki-eyebrow">실무안내 본문</p>
          <h2>제1장 기관전용 사모집합투자기구 개요</h2>
          <p class="wiki-paragraph">제1장은 기관전용 사모집합투자기구가 어떤 제도인지, 왜 도입됐는지, 2021년 체계 개편 후 어떤 기준으로 운용되는지를 확인하는 출발점입니다.</p>
          <nav class="wiki-anchor-list" aria-label="이 문서의 주요 항목">
            <a href="#meaning"><strong>제도의 의의</strong><span>기관전용 사모펀드의 정의와 GP가 수행하는 기능을 확인합니다.</span></a>
            <a href="#background"><strong>도입 배경</strong><span>외환위기 이후 구조조정 수요와 국내 장기 위험자본 육성 필요성을 봅니다.</span></a>
            <a href="#reform"><strong>체계 개편</strong><span>전문투자형·경영참여형 구분에서 일반 사모·기관전용 사모 체계로 바뀐 내용을 정리합니다.</span></a>
            <a href="#investors"><strong>투자자 범위</strong><span>LP로 참여할 수 있는 기관투자자 범위와 일반 개인투자자 제한을 확인합니다.</span></a>
            <a href="#operations"><strong>운용 규제</strong><span>경영참여 의무 폐지, 금전대여, 차입·채무보증 한도를 연결해 봅니다.</span></a>
          </nav>
          <p class="wiki-source-note">출처: <a href="{html_escape(SOURCE_URLS["kvca_guide_file"])}" target="_blank" rel="noreferrer">기관전용 사모집합투자기구 실무안내</a>. 조문 판단은 <a class="wiki-inline-link" href="#law-map">관련 법률·규정</a>에서 시행일과 원천 링크를 함께 확인합니다.</p>
        </section>

        <section class="wiki-section" id="meaning" data-search="제도의 의의 기관전용 사모집합투자기구 정의 GP 운용 경영권 참여 구조조정 성장자본 모험자본">
          <p class="wiki-eyebrow">1-1</p>
          <h2>제도의 의의</h2>
          <div class="wiki-subsection">
            <h3>기관전용 사모집합투자기구의 기능</h3>
            <ul class="wiki-bullet-list">
              <li><strong>기관전용 사모집합투자기구</strong>는 전문성과 위험관리능력을 갖춘 기관투자자 및 이에 준하는 자로부터만 출자를 받아 운용하는 사모집합투자기구입니다.</li>
              <li><a class="wiki-inline-link" href="#term-gp">업무집행사원(GP)</a>이 설립과 운용을 주도하고, 기업의 지분 등에 투자해 경영권 참여, 구조조정, 성장자본 공급 등을 수행합니다.</li>
              <li>투자 후 기업가치를 높이고 그 수익을 사원에게 배분한다는 점에서 국내 모험자본 공급 체계의 핵심 수단으로 기능합니다.</li>
            </ul>
          </div>
          <p class="wiki-related-links">함께 볼 항목: <a href="#investors">투자자 범위</a>, <a href="#actors">주요 주체 및 핵심 용어</a>, <a href="#practice-checklists">실무 체크리스트</a></p>
        </section>

        <section class="wiki-section" id="background" data-search="도입 배경 외환위기 기업 구조조정 위험자본 모험자본 buyout m&a pef 사모투자전문회사">
          <p class="wiki-eyebrow">1-2</p>
          <h2>도입 배경</h2>
          <div class="wiki-subsection">
            <h3>구조조정 수요와 국내 자본 육성</h3>
            <ul class="wiki-bullet-list">
              <li>외환위기 이후 비효율적 지배구조와 취약한 경영능력을 가진 기업에 대한 구조조정 수요가 커졌습니다.</li>
              <li>외국계 사모펀드가 국내 금융기관과 기업 인수·매각에서 적극적으로 움직이면서 국내 장기 위험자본 육성 필요성이 부각됐습니다.</li>
              <li>기존 구조조정 제도는 목적과 투자대상이 좁아 자금조성, 투자, 경영개선, 회수를 한 번에 수행하는 데 한계가 있었습니다.</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>제도 도입과 후속 개편</h3>
            <ul class="wiki-bullet-list">
              <li>2004년 사모투자전문회사 제도가 도입되면서 기관투자자 자금을 기업 인수와 경영개선에 연결하는 제도적 기반이 마련됐습니다.</li>
              <li>2021년 10월 사모펀드 체계개편으로 기존 경영참여형 사모펀드는 기관전용 사모집합투자기구 체계로 재편됐습니다.</li>
            </ul>
          </div>
        </section>

        <section class="wiki-section" id="reform" data-search="사모펀드 체계 개편 일반 사모 기관전용 사모 투자자 범위 위험감수능력 전문투자형 경영참여형 49인 100인">
          <p class="wiki-eyebrow">2</p>
          <h2>사모펀드 체계 개편의 주요 내용</h2>
          <div class="wiki-subsection">
            <h3>분류 기준의 전환</h3>
            <p class="wiki-paragraph">사모펀드를 운용목적에 따라 구분하던 방식에서 투자자의 위험감수능력과 전문성을 기준으로 구분하는 방식으로 개편했습니다.</p>
            <ul class="wiki-bullet-list">
              <li><strong>개정 전</strong>: 전문투자형 사모펀드 / 경영참여형 사모펀드</li>
              <li><strong>개정 후</strong>: 일반 사모집합투자기구 / 기관전용 사모집합투자기구</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>일반 사모와 기관전용 사모의 구분</h3>
            <p class="wiki-paragraph">개편 후 구분의 핵심은 투자자의 전문성과 위험감수능력입니다. 기관전용 사모집합투자기구는 법령상 기관투자자 등으로 인정되는 투자자를 중심으로 운용되므로, LP 적격성 확인은 <a class="wiki-inline-link" href="#investors">투자자 범위</a>와 <a class="wiki-inline-link" href="#fss-reporting">보고 작성 구조</a>에서 함께 봅니다.</p>
          </div>
          <div class="wiki-subsection">
            <h3>특수 목적형 제도와 연결</h3>
            <p class="wiki-paragraph">기관전용 사모집합투자기구는 일반 기관전용 사모펀드를 기본으로 하며, 기업재무안정, 창업·벤처, 기업구조개선, 해외자원개발, 해외농업·산림자원개발, 해외건설 등 특수 목적형 제도가 별도 법률에 따라 운용됩니다.</p>
          </div>
          <p class="wiki-related-links">함께 볼 항목: <a href="#operations">자산운용 규제</a>, <a href="#law-map">관련 법률·규정 지도</a>, <a href="#history">연혁</a></p>
        </section>

        <section class="wiki-section" id="investors" data-search="투자자 범위 lp 유한책임사원 기관투자자 국가 한국은행 금융기관 연기금 공공기관 특수법인 일반 개인투자자 제한 49인 100인">
          <p class="wiki-eyebrow">2-1</p>
          <h2>투자자(LP) 범위</h2>
          <div class="wiki-subsection">
            <h3>참여 가능한 투자자</h3>
            <ul class="wiki-bullet-list">
              <li>기관전용 사모펀드는 법령상 기관투자자 등으로 인정되는 자만 <a class="wiki-inline-link" href="#term-lp">유한책임사원(LP)</a>으로 참여할 수 있습니다.</li>
              <li>국가, 한국은행, 금융기관, 연기금, 공공기관, 이에 준하는 특수법인 등이 주요 투자자 범위에 포함됩니다.</li>
              <li>일반 개인투자자의 참여는 원칙적으로 제한됩니다. 다만 해당 펀드를 운용하는 업무집행사원(GP)의 임원 또는 운용전문인력 등은 예외적으로 참여할 수 있습니다.</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>투자자 수 기준</h3>
            <p class="wiki-paragraph">사모펀드의 투자자 수 기준은 종전 49인 이하에서 100인 이하로 확대되었습니다. 기관전용 사모펀드는 일반 개인투자자가 유입되지 않는 구조를 전제로 하므로, 기관투자자 간 펀드 결성의 자율성이 확대됐습니다.</p>
          </div>
          <p class="wiki-related-links">실무 연결: <a href="#practice-checklists">설립·출자 체크리스트</a>, <a href="#fss-reporting">설립 보고</a>, <a href="#sources">공식 출처</a></p>
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
          <p class="wiki-related-links">실무 연결: <a href="#fss-reporting">운용 중 보고</a>, <a href="#practice-checklists">투자·운용 체크리스트</a>, <a href="#law-map">관련 법률·규정</a></p>
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
          <p class="wiki-related-links">함께 볼 항목: <a href="#meaning">제도의 의의</a>, <a href="#investors">투자자 범위</a>, <a href="#fss-reporting">보고 작성 구조</a></p>
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
          <p class="wiki-related-links">관련 항목: <a href="#history">연혁</a>, <a href="#actors">주요 주체 및 핵심 용어</a></p>
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

        <section class="wiki-section" id="law-map" data-search="관련 법률 규정 자본시장법 시행령 감독규정 특수 목적형 기업재무안정 창업 벤처 기업구조개선 해외자원개발">
          <p class="wiki-eyebrow">법령</p>
          <h2>관련 법률·규정 지도</h2>
          <p class="wiki-paragraph">법령 항목은 조문, 시행일, 관계 업무를 같이 기록합니다. 조문 설명은 업무 판단으로 쓰기 전에 국가법령정보센터 기준 문구와 시행일을 확인합니다.</p>
          <dl class="wiki-definition-list">
            <div><dt>기본 법령</dt><dd><a class="wiki-inline-link" href="#term-capital_markets_act">자본시장법</a>은 기관전용 사모집합투자기구의 정의, 투자자 범위, 업무집행사원 등록, 설립·보고, 운용 기준의 기본 근거입니다.</dd></div>
            <div><dt>하위 규정</dt><dd>시행령, 금융투자업규정, 별표·서식은 투자자 적격성, 운용인력, 보고서 첨부자료처럼 본문 조문만으로 결정하기 어려운 실무 항목을 확인할 때 사용합니다.</dd></div>
            <div><dt>특수 목적형 펀드</dt><dd>기업재무안정, 창업·벤처, 기업구조개선, 해외자원개발, 해외농업·산림자원개발, 해외건설 관련 제도는 목적, 투자대상, 별도 요건을 독립 항목으로 관리합니다.</dd></div>
            <div><dt>개정 이력</dt><dd>2021년 사모펀드 체계 개편처럼 운용 범위와 투자자 보호 장치가 바뀐 개정은 연혁, 조문, 실무 영향으로 나눠 연결합니다.</dd></div>
          </dl>
          <p class="wiki-source-note">기준 원천: 국가법령정보센터, 금융위원회·금융감독원 공지, 금융감독원 「기관전용 사모집합투자기구 실무안내」.</p>
          <p class="wiki-related-links">관련 항목: <a href="#investors">투자자 범위</a>, <a href="#operations">자산운용 규제</a>, <a href="#fss-reporting">보고 작성 구조</a></p>
        </section>

        <section class="wiki-section" id="tax-filings" data-search="세무신고 세무 신고 납부 국세청 홈택스 국세법령정보시스템 원천징수 지급명세서 법인세 소득세 분배 청산 spc lp gp">
          <p class="wiki-eyebrow">세무</p>
          <h2>세무신고·납부 업무 지도</h2>
          <p class="wiki-paragraph">세무 항목은 세목별 결론보다 업무 단계와 증빙 흐름을 먼저 둡니다. 펀드, GP, SPC, LP별로 신고·납부·자료제출 책임을 분리하고, 확정 문구는 국세청·홈택스·국세법령정보시스템 원천이 붙은 항목만 사용합니다.</p>
          <ol class="wiki-event-list">
            <li><strong>주체 확인</strong><span>펀드, 업무집행사원, 투자목적회사, 국내외 유한책임사원, 투자대상회사별로 납세자, 원천징수의무자, 자료제출자를 구분합니다.</span></li>
            <li><strong>거래 유형</strong><span>출자, 투자집행, 이자·배당 수취, 지분 양도, 분배, 청산 분배를 나눠 소득구분과 증빙자료를 연결합니다.</span></li>
            <li><strong>신고 자료</strong><span>원천징수, 지급명세서, 법인세·소득세 관련 자료, 해외투자·외국납부세액 자료처럼 제출 주기와 보관 증빙이 다른 항목을 분리합니다.</span></li>
            <li><strong>검토 기록</strong><span>세무대리인 검토, 예규·판례·질의회신, LP 요청자료, 정정신고 여부를 항목별로 남깁니다.</span></li>
          </ol>
          <p class="wiki-source-note">기준 원천: 국세청, 홈택스, 국세법령정보시스템. 세목별 판단은 최신 법령·예규·실무 검토가 확인된 항목부터 확정합니다.</p>
          <p class="wiki-related-links">관련 항목: <a href="#actors">주요 주체 및 핵심 용어</a>, <a href="#practice-checklists">분배·회수·청산 체크리스트</a>, <a href="#sources">공식 출처</a></p>
        </section>

        <section class="wiki-section" id="fss-reporting" data-search="금감원 보고 금융위원회 보고 작성 설립 보고 변경 보고 정기 보고 즉시 보고 해산 청산 GP 등록 기관전용 사모집합투자기구">
          <p class="wiki-eyebrow">보고</p>
          <h2>금감원·금융위원회 보고 작성 구조</h2>
          <p class="wiki-paragraph">보고 업무는 이벤트, 제출 주체, 법정기한, 제출서식, 접수 증빙, 추가 제출 요청 기록으로 관리합니다. 보고서 문안은 실무안내 본문과 법령 근거가 확인된 단위로 분리합니다.</p>
          <dl class="wiki-definition-list">
            <div><dt>설립 보고</dt><dd>기관전용 사모집합투자기구 설립등기 후 금융위원회 보고가 필요한 이벤트로 관리합니다. 정관, 등기, GP 정보, LP 적격성, 출자약정 자료를 같은 항목에서 확인합니다.</dd></div>
            <div><dt>GP 등록·변경</dt><dd>업무집행사원 등록, 운용전문인력, 대주주·임원·내부통제 변경은 근거 조문과 첨부 증빙을 함께 둡니다.</dd></div>
            <div><dt>운용 중 보고</dt><dd>투자, 차입·채무보증, 투자목적회사, LP 변동, 법령상 즉시·수시 보고 사유는 이벤트별로 별도 체크리스트를 둡니다.</dd></div>
            <div><dt>해산·청산</dt><dd>만기, 해산 결의, 자산 처분, 잔여재산 분배, 청산 등기와 보고 여부를 하나의 종료 흐름으로 관리합니다.</dd></div>
          </dl>
          <p class="wiki-source-note">기준 원천: 금융감독원 실무안내, 국가법령정보센터, 금융위원회·금융감독원 안내자료.</p>
          <p class="wiki-related-links">관련 항목: <a href="#investors">LP 적격성</a>, <a href="#operations">운용 규제</a>, <a href="#practice-checklists">실무 체크리스트</a></p>
        </section>

        <section class="wiki-section" id="practice-checklists" data-search="실무 체크리스트 설립 운용 투자 LP 동의 이해상충 출자약정 납입 분배 회수 청산 보고 제출 증빙">
          <p class="wiki-eyebrow">체크리스트</p>
          <h2>실무 체크리스트</h2>
          <p class="wiki-paragraph">체크리스트는 승인 절차, LP 동의, 제출서류, 접수증, 추가 제출 요청, 사후 보관자료처럼 실제 확인 항목을 기준으로 정리합니다.</p>
          <details class="wiki-foldout" open>
            <summary>설립·출자</summary>
            <ul class="wiki-bullet-list">
              <li>GP 등록 상태, 운용전문인력, 승인권자와 이해상충 검토를 확인합니다.</li>
              <li>정관, 투자계약, 출자약정서, LP 적격성 증빙, 출자 납입 일정을 같은 폴더 기준으로 맞춥니다.</li>
              <li>설립등기, 보고 제출일, 접수번호, 추가 제출 요청 여부를 보고 항목과 연결합니다.</li>
            </ul>
          </details>
          <details class="wiki-foldout">
            <summary>투자·운용</summary>
            <ul class="wiki-bullet-list">
              <li>투자대상 발굴, 실사, 투자심의, 거래구조, LP 자문위원회 또는 동의 필요 여부를 기록합니다.</li>
              <li>차입·채무보증, 금전대여, 투자목적회사, 특수관계자 거래, 투자한도 점검 자료를 보관합니다.</li>
              <li>운용 중 보고 사유와 LP 통지 사유가 발생하면 보고 근거와 발송 증빙을 같이 남깁니다.</li>
            </ul>
          </details>
          <details class="wiki-foldout">
            <summary>분배·회수·청산</summary>
            <ul class="wiki-bullet-list">
              <li>매각 승인, 회수 금액, 분배 기준일, 투자자별 배분표, 세무 검토 자료를 분리하지 않습니다.</li>
              <li>원천징수, 지급명세서, 해외투자 관련 자료, LP별 세무 요청사항을 세무신고 항목과 연결합니다.</li>
              <li>해산 결의, 청산 등기, 최종 보고, 문서 보존기간을 종료 단계 체크리스트로 닫습니다.</li>
            </ul>
          </details>
          <p class="wiki-related-links">관련 항목: <a href="#fss-reporting">보고 작성 구조</a>, <a href="#tax-filings">세무신고·납부</a>, <a href="#law-map">관련 법률·규정</a></p>
        </section>

        <section class="wiki-section" id="sources" data-search="문서 기준 공식 출처 kvca kdi 금융감독원 실무안내 국가법령정보센터 국세청 홈택스 국세법령정보시스템">
          <p class="wiki-eyebrow">출처</p>
          <h2>공식 출처와 확인 경로</h2>
          <p class="wiki-paragraph">기준 문서는 「기관전용 사모집합투자기구 실무안내」 제1장 개관입니다. 법령·세무·보고 항목은 아래 공식 원천에서 시행일, 제출기한, 담당기관을 확인합니다.</p>
          <dl class="wiki-definition-list">
            <div><dt>실무안내</dt><dd>금융감독원 자산운용감독국 실무안내와 공개 게시글을 기준 문서로 둡니다.</dd></div>
            <div><dt>법령 출처</dt><dd>조문 링크, 시행일, 개정 이력을 함께 남깁니다. 시행 전·후 조문은 같은 항목에 섞지 않습니다.</dd></div>
            <div><dt>세무 출처</dt><dd>국세청, 홈택스, 국세법령정보시스템, 예규·질의회신, 세무 검토 기록을 구분합니다.</dd></div>
            <div><dt>보고 출처</dt><dd>금융감독원 실무안내, 금융위원회·금융감독원 공지, 제출서식, 접수 증빙을 연결합니다.</dd></div>
          </dl>
          <ul class="wiki-source-list">
            <li><a href="{html_escape(SOURCE_URLS["kvca_guide_file"])}" target="_blank" rel="noreferrer">기관전용 사모집합투자기구 실무안내 원문</a></li>
            <li><a href="{html_escape(SOURCE_URLS["kvca"])}" target="_blank" rel="noreferrer">KVCA 일반자료실 게시글</a></li>
            <li><a href="{html_escape(SOURCE_URLS["kdi"])}" target="_blank" rel="noreferrer">KDI 경제정보센터 정책자료</a></li>
            <li><a href="{html_escape(SOURCE_URLS["law_capital_markets_act"])}" target="_blank" rel="noreferrer">국가법령정보센터 자본시장법 본문</a></li>
            <li><a href="{html_escape(SOURCE_URLS["fss"])}" target="_blank" rel="noreferrer">금융감독원</a></li>
            <li><a href="{html_escape(SOURCE_URLS["law"])}" target="_blank" rel="noreferrer">국가법령정보센터</a></li>
            <li><a href="{html_escape(SOURCE_URLS["nts"])}" target="_blank" rel="noreferrer">국세청</a></li>
            <li><a href="{html_escape(SOURCE_URLS["hometax"])}" target="_blank" rel="noreferrer">홈택스</a></li>
            <li><a href="{html_escape(SOURCE_URLS["tax_law"])}" target="_blank" rel="noreferrer">국세법령정보시스템</a></li>
          </ul>
        </section>
"""

def _render_sidebar_links() -> str:
    return "\n".join(
        f'          <a href="#{html_escape(anchor)}"><span>{html_escape(label)}</span><small>{html_escape(description)}</small></a>'
        for anchor, label, description in WIKI_SECTIONS
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
    return """    <header class="wiki-app-header" aria-label="PEF Wiki">
      <a class="wiki-brand" href="pef-wiki.html" aria-label="PEF Wiki 홈">
        <span class="wiki-brand-mark" aria-hidden="true">P</span>
        <span>PEF Wiki</span>
      </a>
      <nav class="wiki-service-nav" aria-label="서비스 이동">
        <a href="index.html">브리프</a>
        <a href="lp-notices.html">LP</a>
        <a href="gps.html">GP</a>
        <a class="active" href="pef-wiki.html">Wiki</a>
        <a href="index.html#saved">저장</a>
      </nav>
      <div class="wiki-header-actions">
        <button class="wiki-icon-button" type="button" data-focus-search aria-label="문서 검색">
          <span class="wiki-search-icon" aria-hidden="true"></span>
        </button>
        <button class="wiki-icon-button" type="button" data-toggle-menu aria-label="문서 목차 열기" aria-expanded="false" aria-controls="wiki-mobile-drawer">
          <span class="wiki-menu-icon" aria-hidden="true"></span>
        </button>
      </div>
    </header>
    <nav class="wiki-top-nav" aria-label="Wiki 주제 이동">
      <a class="active" href="#chapter">제1장</a>
      <a href="#law-map">법령</a>
      <a href="#fss-reporting">보고</a>
      <a href="#tax-filings">세무</a>
      <a href="#practice-checklists">체크리스트</a>
      <a href="#sources">출처</a>
    </nav>"""


def _render_mobile_drawer() -> str:
    return f"""    <div class="wiki-drawer-backdrop" data-close-menu hidden></div>
    <aside class="wiki-mobile-drawer" id="wiki-mobile-drawer" aria-label="문서 목차" hidden>
      <div class="wiki-drawer-header">
        <strong>문서 목차</strong>
        <button class="wiki-icon-button" type="button" data-close-menu aria-label="문서 목차 닫기">×</button>
      </div>
      <nav>
{_render_sidebar_links()}
      </nav>
    </aside>"""


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
    html { scroll-behavior: smooth; scroll-padding-top: 118px; }
    body {
      margin: 0;
      background: var(--wiki-bg);
      color: var(--wiki-text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    html.wiki-menu-open {
      overflow: hidden;
    }
    a { color: inherit; }
    .wiki-inline-link {
      border-bottom: 1px solid rgba(31, 107, 99, 0.4);
      color: #164c46;
      font-weight: 650;
      text-decoration: none;
    }
    .wiki-inline-link:hover {
      background: var(--wiki-accent-soft);
    }
    .wiki-shell {
      width: min(1180px, calc(100% - 28px));
      margin: 0 auto;
      padding: 0 0 calc(48px + env(safe-area-inset-bottom));
    }
    .wiki-app-header {
      position: sticky;
      top: 0;
      z-index: 30;
      display: flex;
      gap: 14px;
      align-items: center;
      justify-content: space-between;
      min-height: 56px;
      border-bottom: 1px solid var(--wiki-line);
      background: rgba(255, 255, 255, 0.96);
      backdrop-filter: blur(14px);
    }
    .wiki-brand {
      display: inline-flex;
      gap: 9px;
      align-items: center;
      min-width: 0;
      color: var(--wiki-text);
      font-size: 15px;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }
    .wiki-brand-mark {
      display: inline-grid;
      width: 26px;
      height: 26px;
      place-items: center;
      border: 1px solid #cfd8df;
      border-radius: 6px;
      color: #164c46;
      font-size: 13px;
      font-weight: 700;
    }
    .wiki-service-nav {
      display: none;
      gap: 18px;
      align-items: center;
      min-height: 38px;
      color: var(--wiki-secondary);
      font-size: 13px;
      font-weight: 500;
    }
    .wiki-service-nav a {
      color: inherit;
      text-decoration: none;
    }
    .wiki-service-nav a.active {
      color: var(--wiki-text);
    }
    .wiki-header-actions {
      display: flex;
      gap: 4px;
      align-items: center;
    }
    .wiki-icon-button {
      display: inline-grid;
      width: 36px;
      height: 36px;
      place-items: center;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--wiki-text);
      cursor: pointer;
      text-decoration: none;
    }
    .wiki-icon-button:hover,
    .wiki-icon-button:focus-visible {
      background: var(--wiki-soft);
      outline: none;
    }
    .wiki-search-icon {
      position: relative;
      width: 16px;
      height: 16px;
      border: 2px solid currentColor;
      border-radius: 50%;
    }
    .wiki-search-icon::after {
      position: absolute;
      right: -6px;
      bottom: -4px;
      width: 8px;
      height: 2px;
      background: currentColor;
      border-radius: 2px;
      content: "";
      transform: rotate(45deg);
      transform-origin: left center;
    }
    .wiki-menu-icon,
    .wiki-menu-icon::before,
    .wiki-menu-icon::after {
      display: block;
      width: 18px;
      height: 2px;
      border-radius: 2px;
      background: currentColor;
      content: "";
    }
    .wiki-menu-icon {
      position: relative;
    }
    .wiki-menu-icon::before {
      position: absolute;
      top: -6px;
    }
    .wiki-menu-icon::after {
      position: absolute;
      top: 6px;
    }
    .wiki-top-nav {
      position: sticky;
      top: 56px;
      z-index: 24;
      display: flex;
      gap: 6px;
      overflow-x: auto;
      border-bottom: 1px solid var(--wiki-line);
      padding: 8px 0;
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(14px);
      scrollbar-width: none;
    }
    .wiki-top-nav::-webkit-scrollbar {
      display: none;
    }
    .wiki-top-nav a {
      flex: 0 0 auto;
      min-height: 32px;
      display: inline-flex;
      align-items: center;
      border: 1px solid transparent;
      border-radius: 999px;
      padding: 7px 11px;
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 500;
      text-decoration: none;
    }
    .wiki-top-nav a.active {
      border-color: #cfe4df;
      background: var(--wiki-accent-soft);
      color: #164c46;
    }
    .wiki-doc-header {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 16px;
      padding: 34px 0 24px;
      border-bottom: 1px solid var(--wiki-line);
    }
    .wiki-kicker {
      margin: 0 0 8px;
      color: var(--wiki-accent);
      font-size: 12px;
      font-weight: 600;
    }
    .wiki-doc-header h1 {
      max-width: 880px;
      margin: 0;
      color: var(--wiki-text);
      font-size: 32px;
      line-height: 1.18;
      overflow-wrap: anywhere;
      word-break: keep-all;
    }
    .wiki-lede {
      margin: 10px 0 0;
      color: var(--wiki-secondary);
      font-size: 17px;
      font-weight: 400;
      line-height: 1.55;
    }
    .wiki-search {
      display: grid;
      gap: 6px;
      max-width: 520px;
    }
    .wiki-search label {
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 600;
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
      font-weight: 400;
    }
    .wiki-doc-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 400;
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
    .wiki-sidebar strong {
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 600;
    }
    .wiki-sidebar nav {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 2px;
      scrollbar-width: none;
    }
    .wiki-sidebar nav::-webkit-scrollbar {
      display: none;
    }
    .wiki-sidebar a {
      flex: 0 0 min(220px, 78vw);
      display: grid;
      gap: 3px;
      border-left: 2px solid var(--wiki-line);
      padding: 2px 0 2px 10px;
      color: var(--wiki-text);
      text-decoration: none;
    }
    .wiki-sidebar span {
      font-size: 13px;
      font-weight: 600;
    }
    .wiki-sidebar small {
      color: var(--wiki-secondary);
      font-size: 12px;
      line-height: 1.35;
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
      font-weight: 600;
    }
    .wiki-section h2 {
      margin: 0;
      color: var(--wiki-text);
      font-size: 26px;
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
      font-size: 15px;
      line-height: 1.72;
    }
    .wiki-paragraph {
      max-width: 880px;
    }
    .wiki-anchor-list {
      display: grid;
      gap: 0;
      max-width: 920px;
      margin: 4px 0 0;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-anchor-list a {
      display: grid;
      gap: 4px;
      padding: 10px 0;
      border-bottom: 1px solid var(--wiki-line);
      text-decoration: none;
    }
    .wiki-anchor-list strong {
      color: var(--wiki-text);
      font-size: 14px;
      font-weight: 650;
    }
    .wiki-anchor-list span {
      color: var(--wiki-secondary);
      font-size: 13px;
      line-height: 1.55;
    }
    .wiki-related-links {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 10px;
      max-width: 880px;
    }
    .wiki-related-links a {
      border-bottom: 1px solid rgba(31, 107, 99, 0.4);
      color: #164c46;
      font-weight: 650;
      text-decoration: none;
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
      font-weight: 650;
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
      font-weight: 650;
    }
    .wiki-meta-list dd {
      margin: 0;
    }
    .wiki-stat-list dd {
      color: var(--wiki-text);
      font-weight: 500;
    }
    .wiki-definition-block {
      display: grid;
      gap: 7px;
      padding: 7px 0 4px;
    }
    .wiki-definition-block p {
      max-width: 860px;
    }
    .wiki-source-note {
      margin: 0;
      color: var(--wiki-tertiary);
      font-size: 12px;
      font-weight: 400;
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
      font-weight: 650;
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
      font-weight: 650;
      text-decoration: none;
    }
    .wiki-foldout {
      border-top: 1px solid var(--wiki-line);
      padding: 10px 0;
    }
    .wiki-foldout:last-of-type {
      border-bottom: 1px solid var(--wiki-line);
    }
    .wiki-foldout summary {
      cursor: pointer;
      color: var(--wiki-text);
      font-size: 15px;
      font-weight: 650;
      list-style: none;
    }
    .wiki-foldout summary::-webkit-details-marker {
      display: none;
    }
    .wiki-foldout summary::after {
      content: "+";
      float: right;
      color: var(--wiki-tertiary);
      font-weight: 600;
    }
    .wiki-foldout[open] summary {
      margin-bottom: 8px;
    }
    .wiki-foldout[open] summary::after {
      content: "-";
    }
    .wiki-section[hidden] { display: none; }
    .wiki-drawer-backdrop {
      position: fixed;
      inset: 0;
      z-index: 60;
      background: rgba(23, 32, 42, 0.16);
    }
    .wiki-drawer-backdrop[hidden],
    .wiki-mobile-drawer[hidden] {
      display: none;
    }
    .wiki-mobile-drawer {
      position: fixed;
      top: 0;
      right: 0;
      bottom: 0;
      z-index: 70;
      width: min(86vw, 360px);
      overflow: auto;
      border-left: 1px solid var(--wiki-line);
      background: #ffffff;
      padding: calc(18px + env(safe-area-inset-top)) 18px calc(24px + env(safe-area-inset-bottom));
      box-shadow: -20px 0 50px rgba(15, 23, 42, 0.12);
    }
    .wiki-drawer-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 18px;
    }
    .wiki-drawer-header strong {
      font-size: 17px;
      font-weight: 700;
    }
    .wiki-mobile-drawer nav {
      display: grid;
      gap: 14px;
    }
    .wiki-mobile-drawer a {
      display: grid;
      gap: 4px;
      border-left: 2px solid var(--wiki-line);
      padding-left: 12px;
      color: var(--wiki-text);
      text-decoration: none;
    }
    .wiki-mobile-drawer a span {
      font-size: 15px;
      font-weight: 650;
    }
    .wiki-mobile-drawer a small {
      color: var(--wiki-secondary);
      font-size: 13px;
      line-height: 1.4;
    }
    @media (min-width: 860px) {
      .wiki-service-nav { display: flex; }
      .wiki-doc-header h1 { font-size: 40px; }
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
        top: 118px;
        display: grid;
        gap: 10px;
        border-bottom: 0;
        max-height: calc(100vh - 132px);
        overflow: auto;
        padding: 8px 0;
      }
      .wiki-sidebar strong {
        color: var(--wiki-secondary);
        font-size: 12px;
        font-weight: 600;
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
        font-weight: 600;
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
  const focusSearch = document.querySelector("[data-focus-search]");
  const menuToggle = document.querySelector("[data-toggle-menu]");
  const drawer = document.getElementById("wiki-mobile-drawer");
  const drawerBackdrop = document.querySelector(".wiki-drawer-backdrop");
  const drawerClosers = Array.from(document.querySelectorAll("[data-close-menu]"));
  const topSectionMap = {
    chapter: "chapter",
    meaning: "chapter",
    background: "chapter",
    reform: "chapter",
    investors: "chapter",
    operations: "chapter",
    actors: "chapter",
    market: "chapter",
    history: "chapter",
    "law-map": "law-map",
    "fss-reporting": "fss-reporting",
    "tax-filings": "tax-filings",
    "practice-checklists": "practice-checklists",
    sources: "sources",
  };

  focusSearch?.addEventListener("click", () => {
    search?.focus();
    search?.scrollIntoView({ block: "center", behavior: "smooth" });
  });

  const setMenuOpen = (open) => {
    if (!drawer || !drawerBackdrop || !menuToggle) return;
    drawer.hidden = !open;
    drawerBackdrop.hidden = !open;
    menuToggle.setAttribute("aria-expanded", String(open));
    document.documentElement.classList.toggle("wiki-menu-open", open);
  };

  menuToggle?.addEventListener("click", () => {
    setMenuOpen(drawer?.hidden ?? true);
  });
  drawerClosers.forEach((closer) => closer.addEventListener("click", () => setMenuOpen(false)));
  drawer?.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof Element && target.closest("a")) setMenuOpen(false);
  });

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
    const topId = topSectionMap[id] || id;
    topLinks.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${topId}`));
  }, { rootMargin: "-80px 0px -55% 0px", threshold: [0.1, 0.3, 0.6] });
  sections.forEach((section) => observer.observe(section));
})();
"""
