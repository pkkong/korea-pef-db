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
        "location": "제1장 제2절 p.10",
        "source_label": "KVCA 실무안내",
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
        "location": "제1장 제2절 p.10 · KDI 정책자료",
        "source_label": "KDI 정책자료",
        "source_url": SOURCE_URLS["kdi"],
        "related": ["institutional_private_fund"],
    },
    "gp": {
        "label": "업무집행사원(GP)",
        "type": "역할",
        "location": "제1장 제2절 p.10 · 제3장 GP 등록 제도",
        "source_label": "금융감독원",
        "source_url": SOURCE_URLS["fss"],
        "related": ["lp", "fss_reporting"],
    },
    "lp": {
        "label": "유한책임사원(LP)",
        "type": "역할",
        "location": "제1장 제2절 p.10 · LP 출자공고 서비스",
        "source_label": "KVCA 게시글",
        "source_url": SOURCE_URLS["kvca"],
        "related": ["gp", "institutional_private_fund"],
    },
    "fss_reporting": {
        "label": "설립·변경·해산 보고",
        "type": "규정",
        "location": "관련 장 · 금융감독원 보고 자료",
        "source_label": "금융감독원",
        "source_url": SOURCE_URLS["fss"],
        "related": ["capital_markets_act", "gp"],
    },
    "special_purpose": {
        "label": "특수목적 기관전용 사모펀드",
        "type": "유형",
        "location": "관련 장 · KVCA 실무안내",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["institutional_private_fund"],
    },
    "fund_raising": {
        "label": "자금모집",
        "type": "투자 단계",
        "location": "제1장 제2절 p.11",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["investment", "gp", "lp"],
    },
    "investment": {
        "label": "투자",
        "type": "투자 단계",
        "location": "제1장 제2절 p.11",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["value_addition", "exit"],
    },
    "value_addition": {
        "label": "기업가치 제고",
        "type": "투자 단계",
        "location": "제1장 제2절 p.11",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["investment", "exit"],
    },
    "exit": {
        "label": "매각·회수",
        "type": "투자 단계",
        "location": "제1장 제2절 p.11 · 제1장 제3절 p.17",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["investment", "value_addition"],
    },
    "gp_registration": {
        "label": "GP 등록제",
        "type": "규정",
        "location": "제1장 제4절 p.25",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["gp", "fss_reporting"],
    },
    "leverage": {
        "label": "차입·재무보증",
        "type": "운용 규제",
        "location": "제1장 제4절 p.33",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["capital_markets_act", "money_lending"],
    },
    "money_lending": {
        "label": "금전대여 운용",
        "type": "운용 규제",
        "location": "제1장 제4절 p.33",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["leverage", "capital_markets_act"],
    },
    "financial_group": {
        "label": "금융전업그룹",
        "type": "규정",
        "location": "제1장 제4절 p.28-p.29",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["capital_markets_act", "gp"],
    },
    "investor_count": {
        "label": "투자자 수",
        "type": "투자자 범위",
        "location": "제1장 제4절 p.36",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["lp", "general_vs_institutional"],
    },
}

CHAPTER_SECTIONS = [
    ("chapter", "제1장 개관", "목차"),
    ("background", "제1절 도입 배경", "p.8"),
    ("classification", "제2절 개요 및 분류", "p.10"),
    ("market", "제3절 관련 현황", "p.13"),
    ("history", "제4절 연혁", "p.18"),
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
        <p class="wiki-lede">제1장 개관</p>
      </div>
      <form class="wiki-search" role="search">
        <label for="wikiSearch">문서 검색</label>
        <input id="wikiSearch" type="search" placeholder="예: GP, LP, 자본시장법, 보고">
      </form>
      <div class="wiki-doc-meta" aria-label="문서 기준">
        <span>금융감독원 실무안내</span>
        <span>제1장 p.8-p.36 본문</span>
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


def _render_wiki_article() -> str:
    return f"""
        <section class="wiki-section" id="chapter" data-search="제1장 개관 기관전용 사모집합투자기구 실무안내 pef 목차">
          <p class="wiki-eyebrow">제1장</p>
          <h2>개관</h2>
          <p class="wiki-paragraph">제1장은 사모투자전문회사(PEF) 제도의 도입 배경, 기관전용 사모집합투자기구의 정의와 투자 단계, 시장 성장 현황, 2004년 도입 이후 2021년 사모펀드 체계개편까지의 제도 변화를 한 흐름으로 다룹니다.</p>
          <ol class="wiki-source-index">
            <li><a href="#background">제1절 사모투자전문회사(PEF) 제도 도입 배경</a><span>p.8</span></li>
            <li><a href="#classification">제2절 기관전용 사모집합투자기구 개요 및 분류</a><span>p.10</span></li>
            <li><a href="#market">제3절 기관전용 사모집합투자기구 관련 현황</a><span>p.13</span></li>
            <li><a href="#history">제4절 연혁</a><span>p.18-p.36</span></li>
          </ol>
          <div class="wiki-inline-tools" aria-label="주요 참조">
            <button class="wiki-ref" type="button" data-ref="institutional_private_fund">기관전용 사모집합투자기구</button>
            <button class="wiki-ref" type="button" data-ref="general_vs_institutional">일반 사모 / 기관전용 사모</button>
            <button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button>
            <button class="wiki-ref" type="button" data-ref="gp_registration">GP 등록제</button>
          </div>
        </section>

        <section class="wiki-section" id="background" data-search="도입 배경 외환위기 기업 구조조정 위험자본 buyout m&a crv crf crc">
          <p class="wiki-eyebrow">제1절 · p.8-p.9</p>
          <h2>사모투자전문회사(PEF) 제도 도입 배경</h2>
          <div class="wiki-subsection">
            <h3>1. 기존 투자수단의 한계</h3>
            <ul class="wiki-body-list">
              <li>IMF 외환위기 이후 비효율적 지배구조와 경영능력이 취약한 기업에 대한 대규모 구조조정 수요가 커졌습니다.</li>
              <li>국내 금융기관과 기업의 인수·매각을 통해 거래차익을 실현하려는 외국계 사모펀드, 국내자본 육성, 연기금 등의 대규모 장기 투자 수요가 동시에 확대됐습니다.</li>
              <li>부실기업, 금융기관 부실채권 정리 등을 위해 여러 기업구조조정기구가 마련됐지만 투자대상, 투자방법, 운용주체 자격이 제한돼 범용 구조조정 수단으로 쓰기에는 한계가 있었습니다.</li>
            </ul>
          </div>
          <div class="wiki-subsection">
            <h3>2. 대체 투자수단 도입 필요성</h3>
            <p class="wiki-paragraph">기존 구조조정기구와 달리 자금조성, 투자·운용 전반에 폭넓은 자율성을 부여하는 조합형 구조조정 펀드가 필요해졌고, 2004년 10월 「간접투자자산 운용업법」 개정을 통해 사모투자전문회사 제도의 법적 근거가 마련됐습니다.</p>
          </div>
          <table class="wiki-table">
            <thead><tr><th>구분</th><th>제도상 목적</th><th>한계</th></tr></thead>
            <tbody>
              <tr><td>CRV</td><td>워크아웃 기업 정상화</td><td>금융기관 보유 부실자산 정리에 초점</td></tr>
              <tr><td>CRF</td><td>중소기업 지원과 구조조정</td><td>투자대상과 운용 범위가 제한적</td></tr>
              <tr><td>CRC / 사모 M&A 펀드</td><td>구조조정기업 투자와 M&A 활성화</td><td>목적과 투자방식이 특정 영역에 한정</td></tr>
              <tr><td>CR-REITs</td><td>구조조정 부동산 처분·운용</td><td>부동산 투자 목적에 특화</td></tr>
            </tbody>
          </table>
        </section>

        <section class="wiki-section" id="classification" data-search="개요 분류 일반 사모 기관전용 사모 GP LP 자본시장법 투자단계 자금모집 투자 회수">
          <p class="wiki-eyebrow">제2절 · p.10-p.12</p>
          <h2>기관전용 사모집합투자기구 개요 및 분류</h2>
          <p class="wiki-paragraph">2021년 10월 사모펀드 체계 개편으로 사모펀드는 운용목적이 아니라 투자자 기준으로 구분됩니다. 이 장은 그중 경영권 참여 목적의 기관전용 사모집합투자기구를 중심으로 설명합니다.</p>
          <dl class="wiki-definition-list">
            <div>
              <dt><button class="wiki-ref" type="button" data-ref="institutional_private_fund">기관전용 사모집합투자기구</button></dt>
              <dd>경영권 참여, 사업구조 또는 지배구조 개선 등을 위해 지분증권 등에 투자·운용하는 사모집합투자기구</dd>
            </div>
            <div>
              <dt>사모 발행과 투자자 수</dt>
              <dd>집합투자증권을 사모로 발행하며 투자자 총수는 100인 이하</dd>
            </div>
            <div>
              <dt>투자 성격</dt>
              <dd>투자기업에 적극적으로 경영 참여하고 구조개선 등을 통해 기업가치를 높이는 Buy-out 성격의 펀드</dd>
            </div>
            <div>
              <dt>인적 회사 구조</dt>
              <dd><button class="wiki-ref" type="button" data-ref="gp">무한책임사원</button>과 <button class="wiki-ref" type="button" data-ref="lp">유한책임사원</button>으로 구성되는 partnership</dd>
            </div>
            <div>
              <dt>실체 운영</dt>
              <dd>상근 임직원을 두거나 본점 외 영업소를 설치하지 않는 paper company 형태</dd>
            </div>
          </dl>
          <div class="wiki-subsection">
            <h3>투자 단계</h3>
            <table class="wiki-table">
              <thead><tr><th>단계</th><th>본문 내용</th></tr></thead>
              <tbody>
                <tr><td><button class="wiki-ref" type="button" data-ref="fund_raising">자금모집</button></td><td>업무집행사원이 전문성과 위험감수능력을 갖춘 전문투자자에게 투자 참여를 제안해 자금을 모집</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="investment">투자</button></td><td>투자대상기업 실사와 투자 타당성 검토 후 투자 집행</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="value_addition">기업가치 제고</button></td><td>투자 후 임원 파견, 경영·재무 자문 등을 통해 기업가치 제고</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="exit">매각·회수</button></td><td>지분 매각 또는 증권시장 상장 등을 통해 투자자본 회수</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>기관전용 사모집합투자기구의 분류</h3>
            <table class="wiki-table">
              <thead><tr><th>분류</th><th>근거 법률</th><th>도입 시기</th><th>투자 유형</th></tr></thead>
              <tbody>
                <tr><td>일반 기관전용 사모집합투자기구</td><td>자본시장법</td><td>2004년</td><td>경영권 참여 등</td></tr>
                <tr><td>기업재무안정 기관전용 사모집합투자기구</td><td>자본시장법</td><td>2010년</td><td>재무구조개선기업 투자</td></tr>
                <tr><td>창업·벤처전문 기관전용 사모집합투자기구</td><td>자본시장법</td><td>2016년</td><td>창업·벤처기업 투자</td></tr>
                <tr><td>기업구조개선 기관전용 사모집합투자기구</td><td>산업발전법</td><td>2009년</td><td>구조조정대상기업 투자</td></tr>
                <tr><td>해외자원개발투자전문회사</td><td>해외자원개발사업법</td><td>2006년</td><td>해외자원개발사업 투자</td></tr>
                <tr><td>해외농업자원개발투자전문회사</td><td>해외농업·산림자원 개발협력법</td><td>2011년</td><td>해외농업·산림자원 개발사업 투자</td></tr>
                <tr><td>해외건설 기관전용 사모집합투자기구</td><td>해외건설촉진법</td><td>2016년</td><td>해외건설공사 등 투자</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="wiki-section" id="market" data-search="관련 현황 시장 현황 LP GP 투자대상 감독당국 약정액 이행액 투자 회수">
          <p class="wiki-eyebrow">제3절 · p.13-p.17</p>
          <h2>기관전용 사모집합투자기구 관련 현황</h2>
          <div class="wiki-subsection">
            <h3>1. 개황</h3>
            <p class="wiki-paragraph">국내 기관전용 사모집합투자기구 산업은 준비기, 도약기를 거쳐 2012년부터 투자회수와 운용기간·운용능력 차별화가 진행되는 성장기에 진입한 것으로 제시됩니다.</p>
            <div class="wiki-stat-strip">
              <div><span>2022년말 펀드 수</span><strong>1,098개</strong></div>
              <div><span>약정액</span><strong>125.3조원</strong></div>
              <div><span>이행액</span><strong>97.1조원</strong></div>
            </div>
          </div>
          <div class="wiki-subsection">
            <h3>2. 업무집행사원(GP) 현황</h3>
            <p class="wiki-paragraph">2022년 12월말 기준 기관전용 사모집합투자기구를 운용 중인 업무집행사원은 총 415사입니다. 성장기에는 투자실적 가시화와 운용능력 차별화가 진행되면서 전문운용사 위주의 산업으로 재편된 흐름이 나타납니다.</p>
            <table class="wiki-table">
              <thead><tr><th>GP 유형</th><th>2005년</th><th>2012년</th><th>2022년</th></tr></thead>
              <tbody>
                <tr><td>전문운용사</td><td>7사</td><td>69사</td><td>312사</td></tr>
                <tr><td>금융회사</td><td>7사</td><td>46사</td><td>46사</td></tr>
                <tr><td>창투계 회사</td><td>-</td><td>26사</td><td>57사</td></tr>
                <tr><td>총계</td><td>14사</td><td>141사</td><td>415사</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>3. 자금모집·투자·회수</h3>
            <table class="wiki-table">
              <thead><tr><th>항목</th><th>2022년 12월말 기준</th><th>본문상 흐름</th></tr></thead>
              <tbody>
                <tr><td><button class="wiki-ref" type="button" data-ref="fund_raising">자금모집</button></td><td>약정액 125.3조원</td><td>연기금 등 기관투자자 기반 확대 후 2021년 누적 자금모집 규모 100조원 돌파</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="investment">투자</button></td><td>누적 투자규모 192.4조원</td><td>전문인력 보유 펀드는 전략적 투자, 금융회사 운용 펀드는 재무적 투자 중심</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="exit">회수</button></td><td>누적 투자회수 금액 108.5조원</td><td>투자 회수와 해산이 본격화되면서 성과 검증 가능성이 확대</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-link-row">
            <button class="wiki-ref" type="button" data-ref="lp">LP</button>
            <button class="wiki-ref" type="button" data-ref="gp">GP</button>
            <button class="wiki-ref" type="button" data-ref="fss_reporting">감독·보고</button>
          </div>
        </section>

        <section class="wiki-section" id="history" data-search="연혁 2004 2006 2007 2009 2010 2013 2015 2021 사모펀드 제도 개편">
          <p class="wiki-eyebrow">제4절 · p.18-p.36</p>
          <h2>연혁</h2>
          <div class="wiki-subsection">
            <h3>1. 간접투자자산 운용업법 및 시행령</h3>
            <ol class="wiki-event-list">
              <li><strong>2004년 12월</strong><span>합자회사(Limited Partnership) 형태의 사모투자전문회사 제도 도입. 손익분배, 업무범위, 펀드운용 규제완화, 대기업집단 제한, 지주회사 규제 등에서 기존 사모 M&A 펀드와 구분되는 체계를 마련했습니다.</span></li>
              <li><strong>2006년 4월</strong><span>유한책임사원의 최소 출자가액 완화, PEF 자산운용 범위 확대, 의무투자비율 완화가 반영됐습니다.</span></li>
              <li><strong>2007년 12월</strong><span>국내 PEF가 해외 회사 또는 SPC 등을 통해 해외 자산에 투자할 수 있도록 규제가 정비됐고, 해외 부실채권 투자도 허용됐습니다.</span></li>
            </ol>
          </div>
          <div class="wiki-subsection">
            <h3>2. 자본시장법 및 시행령</h3>
            <ol class="wiki-event-list">
              <li><strong>2009년 2월</strong><span>투자목적회사 주주·사원 범위 확대, PEF 등록 공고 의무, 여유자금 운용방법 확대, 상호출자제한기업집단 관련 제한 완화, 비금융주력자 보유제한 규정 삭제, 운용규제 합리화가 진행됐습니다.</span></li>
              <li><strong>2010년 6월</strong><span><button class="wiki-ref" type="button" data-ref="special_purpose">기업재무안정 PEF</button> 제도가 도입돼 재무구조개선기업 등에 대한 민간 자금 공급 통로가 마련됐습니다.</span></li>
              <li><strong>2013년 8월</strong><span>투자 가능한 주권 관련 사채권 범위 확대, <button class="wiki-ref" type="button" data-ref="gp_registration">업무집행사원 등록제</button> 도입, 유한책임사원의 재산운용 관여 금지 명확화, PEF 보고의무 신설 등 규제체계가 선진화됐습니다.</span></li>
              <li><strong>2015년 10월</strong><span>사모펀드 규율체계 정비와 적격투자자 범위 설정, 업무집행사원 감독 강화, 설립규제 완화, <button class="wiki-ref" type="button" data-ref="financial_group">금융전업그룹</button> 규제 합리화, 운용규제 완화가 반영됐습니다.</span></li>
              <li><strong>2021년 10월</strong><span>사모펀드 시장의 신뢰와 투자자 보호 장치를 강화하면서 전문투자형·경영참여형 체계를 일반 사모펀드와 기관전용 사모펀드 체계로 개편했습니다.</span></li>
            </ol>
          </div>
          <div class="wiki-subsection">
            <h3>3. 2021년 사모펀드 체계개편 주요 내용</h3>
            <table class="wiki-table">
              <thead><tr><th>주제</th><th>본문 내용</th></tr></thead>
              <tbody>
                <tr><td>분류체계</td><td>운용목적 기준에서 투자자 범위 기준으로 변경. 전문투자자와 경영참여형의 구분은 일반 사모펀드와 기관전용 사모펀드 구분으로 재편</td></tr>
                <tr><td>운용규제</td><td>기관전용 사모집합투자기구는 경영참여 목적 운용의무가 폐지되고 일반 사모펀드와 동일한 운용규제 적용</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="leverage">차입·재무보증</button></td><td>집합투자기구 및 투자목적회사를 합산해 400%까지 차입 허용, 거래 실질 기준 산정 방식 반영</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="money_lending">금전대여</button></td><td>대출 방식의 자산운용을 허용하되 개인대출·사행성 업종 관련 대출은 제한</td></tr>
                <tr><td>경영참여목적 투자요건</td><td>경영참여 목적 투자 시 15년 내 처분의무 등 기존 의무투자기간 관련 규정 폐지</td></tr>
                <tr><td>GP 관리·감독</td><td>투자운용전문인력 요건 강화, 재무제표 제출, 변경보고, 감독·검사, 불건전행위 규율 강화</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="investor_count">투자자 수</button></td><td>사모집합투자기구 투자자 수 기준을 49인에서 최대 100인까지 확대. 일반투자자 수는 49인으로 유지</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="wiki-section" id="rules" data-search="법령 규정 감독 보고 설립 변경 해산 특수목적">
          <p class="wiki-eyebrow">참조</p>
          <h2>법령·규정 참조</h2>
          <div class="wiki-reference-grid">
            <button class="wiki-reference-row" type="button" data-ref="capital_markets_act"><span>법령</span><strong>자본시장법</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="gp_registration"><span>규정</span><strong>GP 등록제</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="fss_reporting"><span>규정</span><strong>설립·변경·해산 보고</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="special_purpose"><span>유형</span><strong>특수목적 기관전용 사모펀드</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="leverage"><span>운용</span><strong>차입·재무보증</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="money_lending"><span>운용</span><strong>금전대여 운용</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="financial_group"><span>규정</span><strong>금융전업그룹</strong></button>
            <button class="wiki-reference-row" type="button" data-ref="investor_count"><span>투자자</span><strong>투자자 수</strong></button>
          </div>
        </section>

        <section class="wiki-section" id="sources" data-search="출처 kvca kdi 금융감독원 실무안내">
          <p class="wiki-eyebrow">출처</p>
          <h2>공식 출처</h2>
          <p class="wiki-paragraph">기준 문서: 「기관전용 사모집합투자기구 실무안내」 제1장 p.8-p.36.</p>
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
    .wiki-doc-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      align-items: center;
      color: var(--wiki-secondary);
      font-size: 12px;
      font-weight: 850;
    }
    .wiki-doc-meta span {
      min-height: 30px;
      display: inline-flex;
      align-items: center;
      border-bottom: 1px solid var(--wiki-line);
      padding: 5px 10px;
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
    .wiki-section h3 {
      margin: 0;
      color: var(--wiki-text);
      font-size: 18px;
      line-height: 1.35;
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
    .wiki-stat-strip {
      display: grid;
      gap: 0;
      border-top: 1px solid var(--wiki-line);
      border-bottom: 1px solid var(--wiki-line);
    }
    .wiki-stat-strip div {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 12px 0;
      border-bottom: 1px solid var(--wiki-line);
    }
    .wiki-stat-strip div:last-child { border-bottom: 0; }
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
      gap: 0;
      margin: 0;
      padding: 0;
      list-style: none;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-source-index li {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 66px;
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
    .wiki-timeline,
    .wiki-event-list {
      display: grid;
      gap: 0;
      margin: 0;
      padding: 0;
      list-style: none;
      border-top: 1px solid var(--wiki-line);
    }
    .wiki-timeline li,
    .wiki-event-list li {
      display: grid;
      gap: 5px;
      border-bottom: 1px solid var(--wiki-line);
      padding: 13px 0;
    }
    .wiki-timeline strong,
    .wiki-event-list strong {
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
    .bottom-nav.newsletter-only {
      background: rgba(255, 255, 255, 0.98);
      box-shadow: 0 -10px 30px rgba(15, 23, 42, 0.08);
    }
    @media (min-width: 860px) {
      .wiki-hero {
        grid-template-columns: minmax(0, 1fr) minmax(320px, 0.45fr);
        align-items: end;
      }
      .wiki-doc-meta { grid-column: 1 / -1; }
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
      .wiki-timeline li,
      .wiki-event-list li {
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
