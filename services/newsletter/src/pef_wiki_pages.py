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
        "location": "제1장 제2절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["general_vs_institutional", "gp", "lp"],
        "summary": "집합투자증권을 사모로 발행하고 투자자 총수가 100인 이하인 사모집합투자기구 중 기관전용 체계에 속하는 투자기구입니다.",
        "checkpoints": ["투자자 범위와 투자자 수 기준", "GP·LP 사원 구조", "경영권 참여 외 운용전략 허용 여부"],
    },
    "capital_markets_act": {
        "label": "자본시장법",
        "type": "법령",
        "location": "국가법령정보센터 현행 법령",
        "source_label": "국가법령정보센터",
        "source_url": SOURCE_URLS["law"],
        "related": ["fss_reporting", "gp"],
        "summary": "기관전용 사모집합투자기구의 정의, 투자자 수, 업무집행사원, 보고·감독 체계의 기본 근거가 되는 법률입니다.",
        "checkpoints": ["제9조 정의 조항", "제249조의11 이하 기관전용 사모집합투자기구 조항", "시행령·감독규정 위임사항"],
    },
    "general_vs_institutional": {
        "label": "일반 사모 / 기관전용 사모",
        "type": "분류",
        "location": "제1장 제2절 · KDI 정책자료",
        "source_label": "KDI 정책자료",
        "source_url": SOURCE_URLS["kdi"],
        "related": ["institutional_private_fund"],
    },
    "gp": {
        "label": "업무집행사원(GP)",
        "type": "역할",
        "location": "제1장 제2절 · 제3장 GP 등록 제도",
        "source_label": "금융감독원",
        "source_url": SOURCE_URLS["fss"],
        "related": ["lp", "fss_reporting"],
        "summary": "펀드의 자금모집, 투자대상 발굴, 실사, 투자집행, 사후관리, 회수와 보고를 집행하는 사원입니다.",
        "checkpoints": ["전문인력과 내부통제", "출자자 보고와 이해상충 관리", "GP 등록·변경보고 이력"],
    },
    "lp": {
        "label": "유한책임사원(LP)",
        "type": "역할",
        "location": "제1장 제2절 · LP 출자공고 서비스",
        "source_label": "KVCA 게시글",
        "source_url": SOURCE_URLS["kvca"],
        "related": ["gp", "institutional_private_fund"],
        "summary": "펀드에 출자약정을 제공하고 손익을 배분받는 투자자입니다. 운용은 GP가 담당하고 LP는 약정 범위에서 책임을 부담합니다.",
        "checkpoints": ["출자약정액과 납입 조건", "투자자 적격성", "LPAC 등 운용 관여 범위"],
    },
    "fss_reporting": {
        "label": "설립·변경·해산 보고",
        "type": "규정",
        "location": "관련 장 · 금융감독원 보고 자료",
        "source_label": "금융감독원",
        "source_url": SOURCE_URLS["fss"],
        "related": ["capital_markets_act", "gp"],
        "summary": "기관전용 사모집합투자기구는 설립, 운용 중 주요 변경, 해산·청산 단계에서 감독당국 보고 체계를 따라야 합니다.",
        "checkpoints": ["설립보고", "정관·사원·GP 변경보고", "해산 및 청산 보고"],
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
        "location": "제1장 제2절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["investment", "gp", "lp"],
        "summary": "GP가 전문성과 위험감수능력을 갖춘 투자자에게 출자를 제안하고 출자약정을 확보하는 단계입니다.",
        "checkpoints": ["약정총액", "출자자 구성", "납입 방식과 투자기간"],
    },
    "investment": {
        "label": "투자",
        "type": "투자 단계",
        "location": "제1장 제2절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["value_addition", "exit"],
        "summary": "투자대상기업의 구체적 정보를 확보하고 투자 타당성 검토 후 거래구조를 확정해 집행하는 단계입니다.",
        "checkpoints": ["실사 범위", "SPC·인수금융 구조", "투자심의와 의사결정 기록"],
    },
    "value_addition": {
        "label": "기업가치 제고",
        "type": "투자 단계",
        "location": "제1장 제2절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["investment", "exit"],
        "summary": "투자 후 임원 파견, 경영·재무 자문, 사업구조 또는 지배구조 개선으로 기업가치를 높이는 단계입니다.",
        "checkpoints": ["이사회 권한", "재무개선 계획", "사업재편과 내부통제"],
    },
    "exit": {
        "label": "매각·회수",
        "type": "투자 단계",
        "location": "제1장 제2절 · 제1장 제3절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["investment", "value_addition"],
        "summary": "지분 매각, 전략적·재무적 투자자 매각, 상장 등을 통해 투자자본을 회수하는 단계입니다.",
        "checkpoints": ["회수 방식", "분배 구조", "해산·청산 일정"],
    },
    "gp_registration": {
        "label": "GP 등록제",
        "type": "규정",
        "location": "제1장 제4절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["gp", "fss_reporting"],
        "summary": "업무집행사원의 전문성, 인력, 재무·내부통제 요건을 확인해 운용사 시장을 관리하는 장치입니다.",
        "checkpoints": ["등록요건", "전문인력 요건", "변경보고와 검사 리스크"],
    },
    "leverage": {
        "label": "차입·재무보증",
        "type": "운용 규제",
        "location": "제1장 제4절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["capital_markets_act", "money_lending"],
        "summary": "2021년 제도개편 이후 기관전용 사모펀드는 펀드와 투자목적회사를 합산한 기준으로 차입·재무보증 한도를 봅니다.",
        "checkpoints": ["합산 400% 한도", "SPC 포함 여부", "거래 실질 기준 산정"],
    },
    "money_lending": {
        "label": "금전대여 운용",
        "type": "운용 규제",
        "location": "제1장 제4절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["leverage", "capital_markets_act"],
        "summary": "대출 방식 운용이 허용됐지만 개인대출과 사행성 업종 관련 대출은 제한됩니다.",
        "checkpoints": ["차주와 업종 제한", "펀드 문서상 투자전략", "리스크 관리와 LP 보고"],
    },
    "financial_group": {
        "label": "금융전업그룹",
        "type": "규정",
        "location": "제1장 제4절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["capital_markets_act", "gp"],
    },
    "investor_count": {
        "label": "투자자 수",
        "type": "투자자 범위",
        "location": "제1장 제4절",
        "source_label": "KVCA 실무안내",
        "source_url": SOURCE_URLS["kvca_pdf"],
        "related": ["lp", "general_vs_institutional"],
        "summary": "사모집합투자기구 투자자 수 기준은 최대 100인까지 확대됐고, 일반투자자 수 기준은 별도로 관리됩니다.",
        "checkpoints": ["전체 투자자 수", "일반투자자 수", "특수관계·명의 기준 검토"],
    },
}

CHAPTER_SECTIONS = [
    ("chapter", "제1장 개관", "목차"),
    ("background", "제1절 도입 배경", "제도 도입 논리"),
    ("classification", "제2절 개요 및 분류", "정의·구조·유형"),
    ("market", "제3절 관련 현황", "시장·GP·회수"),
    ("history", "제4절 연혁", "제도 변화"),
    ("rules", "법령·규정", "참조"),
    ("sources", "문서 기준", "기준 자료"),
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
  <aside class="wiki-ref-panel" id="wikiRefPanel" aria-label="참조 상세" aria-live="polite" hidden>
    <button class="wiki-ref-close" type="button" aria-label="닫기"></button>
    <span id="wikiRefType"></span>
    <h2 id="wikiRefTitle"></h2>
    <p id="wikiRefLocation"></p>
    <p id="wikiRefSummary"></p>
    <ul class="wiki-ref-checklist" id="wikiRefChecklist"></ul>
    <div class="wiki-ref-related" id="wikiRefRelated"></div>
    <a id="wikiRefSource" href="{html_escape(SOURCE_URLS["kvca_pdf"])}" target="_blank" rel="noreferrer">자료 열기</a>
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
          <p class="wiki-paragraph">제1장은 사모투자전문회사 제도가 도입된 배경, 기관전용 사모집합투자기구의 정의와 분류, 국내 시장 규모와 GP 현황, 2004년 도입 이후 2021년 사모펀드 체계개편까지의 흐름을 연결합니다.</p>
          <div class="wiki-subsection" id="chapter-fast-index">
            <h3>바로 찾기</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>찾는 항목</th><th>이동</th><th>같이 볼 용어</th></tr></thead>
              <tbody>
                <tr><td>기관전용 사모펀드의 법적 정의</td><td><a href="#legal-definition">정의와 요건</a></td><td><button class="wiki-ref" type="button" data-ref="institutional_private_fund">기관전용 사모집합투자기구</button></td></tr>
                <tr><td>GP·LP·SPC 역할</td><td><a href="#operating-structure">기본 운용구조</a></td><td><button class="wiki-ref" type="button" data-ref="gp">GP</button> · <button class="wiki-ref" type="button" data-ref="lp">LP</button></td></tr>
                <tr><td>출자약정액·이행액·GP 수</td><td><a href="#market-scale">시장 규모 변화</a></td><td><button class="wiki-ref" type="button" data-ref="fund_raising">자금모집</button></td></tr>
                <tr><td>2021년 제도개편</td><td><a href="#reform-2021">개편 전후 실무 포인트</a></td><td><button class="wiki-ref" type="button" data-ref="leverage">차입·재무보증</button> · <button class="wiki-ref" type="button" data-ref="investor_count">투자자 수</button></td></tr>
              </tbody>
            </table>
          </div>
          <ol class="wiki-source-index">
            <li><a href="#background">제1절 사모투자전문회사 제도 도입 배경</a><span>도입 논리</span></li>
            <li><a href="#classification">제2절 기관전용 사모집합투자기구 개요 및 분류</a><span>정의·구조</span></li>
            <li><a href="#market">제3절 기관전용 사모집합투자기구 관련 현황</a><span>시장 현황</span></li>
            <li><a href="#history">제4절 연혁</a><span>제도 변화</span></li>
          </ol>
          <div class="wiki-inline-tools" aria-label="주요 참조">
            <button class="wiki-ref" type="button" data-ref="institutional_private_fund">기관전용 사모집합투자기구</button>
            <button class="wiki-ref" type="button" data-ref="general_vs_institutional">일반 사모 / 기관전용 사모</button>
            <button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button>
            <button class="wiki-ref" type="button" data-ref="gp_registration">GP 등록제</button>
          </div>
        </section>

        <section class="wiki-section" id="background" data-search="도입 배경 외환위기 기업 구조조정 위험자본 buyout m&a crv crf crc">
          <p class="wiki-eyebrow">제1절</p>
          <h2>사모투자전문회사(PEF) 제도 도입 배경</h2>
          <p class="wiki-paragraph">제도 도입의 출발점은 외환위기 이후 커진 기업 구조조정 수요와 장기 위험자본 공급 필요성입니다. 기존 구조조정 수단은 특정 목적과 대상에 묶여 있었고, 민간 자본이 기업 인수·경영개선·회수까지 일관되게 수행하기에는 운용 자율성이 부족했습니다.</p>
          <div class="wiki-subsection">
            <h3>제도 도입 배경 요인</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>요인</th><th>내용</th><th>PEF 제도와의 연결</th></tr></thead>
              <tbody>
                <tr><td>구조조정 수요</td><td>외환위기 이후 비효율적 지배구조와 취약한 경영능력을 가진 기업에 대한 대규모 구조조정 필요가 커졌습니다.</td><td>단순 채권정리나 청산 중심이 아니라 지배구조 개선과 기업가치 제고를 수행할 수 있는 투자기구가 필요했습니다.</td></tr>
                <tr><td>국내 자본 육성</td><td>외국계 사모펀드가 국내 금융기관·기업 인수와 매각에서 적극적으로 움직이면서 국내 장기 위험자본 육성 필요가 부각됐습니다.</td><td>연기금과 기관투자자의 장기 자금을 기업 인수·개선·회수 구조로 연결하는 통로가 요구됐습니다.</td></tr>
                <tr><td>기존 제도 한계</td><td>부실채권 정리, 워크아웃, 구조조정 부동산 등 목적별 제도는 있었지만 투자대상·투자방법·운용주체 자격이 좁았습니다.</td><td>자금조성부터 투자, 경영개선, 회수까지 폭넓은 재량을 가진 조합형 투자기구가 필요했습니다.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>기존 기업구조조정 수단 비교</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>구분</th><th>주요 목적</th><th>투자·운용 범위</th><th>PEF 도입 필요성과의 차이</th></tr></thead>
              <tbody>
                <tr><td>CRV</td><td>워크아웃 기업 정상화</td><td>금융기관이 보유한 부실자산과 구조조정 대상 기업 중심</td><td>부실 정리 목적이 강하고 범용 인수·경영개선 투자기구로 쓰기 어렵습니다.</td></tr>
                <tr><td>CRF</td><td>중소기업 지원과 구조조정</td><td>중소기업 구조조정과 관련된 제한된 투자영역</td><td>자금모집과 운용 범위가 넓은 기관투자자형 펀드 구조와 다릅니다.</td></tr>
                <tr><td>CRC</td><td>구조조정기업 인수·정리</td><td>구조조정 전문회사 중심의 기업 구조조정 업무</td><td>운용주체와 대상이 제한돼 다양한 기업 인수·개선 전략을 담기 어렵습니다.</td></tr>
                <tr><td>사모 M&A 펀드</td><td>기업 인수·합병 활성화</td><td>M&A 목적 투자에 초점</td><td>기업가치 제고와 회수까지 포괄하는 장기 조합형 구조가 제한적입니다.</td></tr>
                <tr><td>CR-REITs</td><td>구조조정 부동산 처분·운용</td><td>부동산 자산 중심</td><td>기업 지분 투자와 경영참여를 수행하는 PEF와 투자대상이 다릅니다.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>제도 도입의 결론</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>필요 기능</th><th>기존 수단의 한계</th><th>PEF 제도에서 기대한 역할</th></tr></thead>
              <tbody>
                <tr><td>자금조성</td><td>목적별 기구 중심이라 대규모 장기자금 모집에 제약</td><td>기관투자자 자금을 모아 기업 인수·개선에 투입</td></tr>
                <tr><td>투자운용</td><td>투자대상과 방법이 법령·목적별로 세분화</td><td>지분투자, 경영참여, 구조개선 등 폭넓은 운용 허용</td></tr>
                <tr><td>회수</td><td>청산 또는 특정 자산 처분 중심</td><td>기업가치 제고 후 매각·상장 등 다양한 회수 전략 사용</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="wiki-section" id="classification" data-search="개요 분류 일반 사모 기관전용 사모 GP LP 자본시장법 투자단계 자금모집 투자 회수">
          <p class="wiki-eyebrow">제2절</p>
          <h2>기관전용 사모집합투자기구 개요 및 분류</h2>
          <p class="wiki-paragraph">2021년 10월 사모펀드 체계개편 이후 사모펀드는 운용목적이 아니라 투자자 범위를 기준으로 일반 사모와 기관전용 사모로 구분됩니다. 과거 PEF가 경영참여형 사모펀드로 출발했다는 역사와, 현재 기관전용 사모집합투자기구가 더 넓은 운용전략을 사용할 수 있다는 점을 구분해 읽어야 합니다.</p>
          <div class="wiki-subsection" id="legal-definition">
            <h3>법적 정의와 성립 요건</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>요소</th><th>내용</th><th>실무상 확인할 점</th></tr></thead>
              <tbody>
                <tr><td>법적 근거</td><td><button class="wiki-ref" type="button" data-ref="capital_markets_act">자본시장법</button>상 사모집합투자기구 정의와 기관전용 사모집합투자기구 특례 조항</td><td>정관, 사원 구성, 투자자 수, GP 등록·보고 의무를 같은 체계에서 확인합니다.</td></tr>
                <tr><td>모집 방식</td><td>집합투자증권을 사모로 발행</td><td>공모가 아니라 제한된 투자자에게 출자 참여를 제안합니다.</td></tr>
                <tr><td>투자자 수</td><td>투자자 총수 100인 이하</td><td><button class="wiki-ref" type="button" data-ref="investor_count">투자자 수</button> 산정 기준과 일반투자자 포함 여부를 별도로 점검합니다.</td></tr>
                <tr><td>사원 구조</td><td><button class="wiki-ref" type="button" data-ref="gp">업무집행사원</button>과 <button class="wiki-ref" type="button" data-ref="lp">유한책임사원</button>으로 구성되는 partnership 구조</td><td>운용 책임, 출자 책임, 운용 관여 제한, 보고권한을 사원별로 분리합니다.</td></tr>
                <tr><td>회사 실체</td><td>상근 임직원이나 본점 외 영업소를 두지 않는 paper company 형태</td><td>펀드 자체보다 GP의 인력, 내부통제, 이해상충 관리 체계가 실질 심사 대상입니다.</td></tr>
                <tr><td>운용전략</td><td>경영권 참여, 사업구조·지배구조 개선 투자에서 출발했으나 2021년 개편 이후 운용규제가 일반 사모와 일원화</td><td>현재 문서에서는 과거 PEF의 buy-out 성격과 현행 기관전용 사모의 허용전략을 분리해 봅니다.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection" id="operating-structure">
            <h3>기본 운용구조</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>주체</th><th>역할</th><th>연결 관계</th></tr></thead>
              <tbody>
                <tr><td>LP</td><td>출자약정과 납입을 통해 펀드 자금을 공급하고 손익을 배분받는 투자자</td><td>GP와 사원 관계를 맺고 펀드 운용 결과를 부담합니다.</td></tr>
                <tr><td>GP</td><td>투자대상 발굴, 실사, 투자집행, 사후관리, 회수 등 운용 업무 수행</td><td>무한책임사원으로 펀드 운용과 보고의 중심이 됩니다.</td></tr>
                <tr><td>SPC</td><td>투자목적회사로 특정 투자대상에 대한 인수·투자 구조를 담는 중간 기구</td><td>필요 시 펀드와 투자대상회사 사이에 위치합니다.</td></tr>
                <tr><td>투자대상회사</td><td>지분투자, 경영참여, 사업구조·지배구조 개선의 대상</td><td>기업가치 제고 후 매각 또는 상장 등을 통해 회수합니다.</td></tr>
                <tr><td>감독·보고 체계</td><td>설립, 변경, 해산, GP 등록과 운용 관련 보고·감독</td><td>자본시장법과 금융감독원 보고 체계를 통해 관리됩니다.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>투자 단계</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>단계</th><th>주요 업무</th><th>실무상 확인할 항목</th></tr></thead>
              <tbody>
                <tr><td><button class="wiki-ref" type="button" data-ref="fund_raising">자금모집</button></td><td>GP가 전문성과 위험감수능력을 갖춘 전문투자자에게 투자 참여를 제안하고 출자약정을 확보</td><td>출자자 구성, 약정총액, 납입조건, 투자기간, 관리보수·성과보수 구조</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="investment">투자</button></td><td>투자대상기업 발굴, 실사, 투자 타당성 검토, 거래구조 설계와 투자 집행</td><td>인수 대상, 지분율, 인수금융, SPC 사용 여부, 투자심의 절차</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="value_addition">기업가치 제고</button></td><td>임원 파견, 경영·재무 자문, 사업구조 또는 지배구조 개선을 통해 기업가치 제고</td><td>사후관리 계획, 이사회 권한, 재무개선, 사업재편, 내부통제</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="exit">매각·회수</button></td><td>지분 매각, 전략적 투자자 매각, 재무적 투자자 매각, 상장 등을 통한 투자자본 회수</td><td>회수시점, 회수방식, 분배구조, 잔여자산 처리, 해산 절차</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection" id="general-vs-institutional">
            <h3>일반 사모와 기관전용 사모의 구분</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>구분</th><th>일반 사모집합투자기구</th><th>기관전용 사모집합투자기구</th><th>실무상 차이</th></tr></thead>
              <tbody>
                <tr><td>구분 기준</td><td>전문투자자와 일정 범위 일반투자자를 대상으로 하는 사모펀드</td><td>기관투자자 등 제한된 투자자를 중심으로 하는 사모펀드</td><td>2021년 개편 후 운용목적보다 투자자 범위가 핵심 구분 기준입니다.</td></tr>
                <tr><td>운용 주체</td><td>일반 사모펀드 운용사</td><td><button class="wiki-ref" type="button" data-ref="gp">업무집행사원(GP)</button></td><td>GP 등록, 전문인력, 변경보고 이슈가 기관전용에서 중요합니다.</td></tr>
                <tr><td>투자자 관리</td><td>일반투자자 보호 장치와 판매 규율이 중요</td><td><button class="wiki-ref" type="button" data-ref="lp">LP</button>의 전문성, 출자약정, 운용 관여 제한이 중요</td><td>LP 출자공고와 펀드 문서에서 투자자 지위가 명확해야 합니다.</td></tr>
                <tr><td>데이터 연결</td><td>상품·판매·수탁 관련 데이터</td><td>GP, LP, 펀드, 투자대상회사, 회수성과 데이터</td><td>이 서비스에서는 기관전용 사모의 LP·GP·딜 데이터를 우선 연결합니다.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>기관전용 사모집합투자기구의 분류</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>분류</th><th>근거 법률</th><th>도입 시기</th><th>투자 유형</th><th>주요 목적</th></tr></thead>
              <tbody>
                <tr><td>일반 기관전용 사모집합투자기구</td><td>자본시장법</td><td>2004년</td><td>경영권 참여 등</td><td>일반 기업 인수·경영개선·회수</td></tr>
                <tr><td>기업재무안정 기관전용 사모집합투자기구</td><td>자본시장법</td><td>2010년</td><td>재무구조개선기업 투자</td><td>재무구조 개선이 필요한 기업에 민간 자금 공급</td></tr>
                <tr><td>창업·벤처전문 기관전용 사모집합투자기구</td><td>자본시장법</td><td>2016년</td><td>창업·벤처기업 투자</td><td>벤처·창업기업 성장자금 공급</td></tr>
                <tr><td>기업구조개선 기관전용 사모집합투자기구</td><td>산업발전법</td><td>2009년</td><td>구조조정대상기업 투자</td><td>산업 구조조정과 기업구조개선 지원</td></tr>
                <tr><td>해외자원개발투자전문회사</td><td>해외자원개발사업법</td><td>2006년</td><td>해외자원개발사업 투자</td><td>해외 자원개발 프로젝트 투자</td></tr>
                <tr><td>해외농업자원개발투자전문회사</td><td>해외농업·산림자원 개발협력법</td><td>2011년</td><td>해외농업·산림자원 개발사업 투자</td><td>해외 농업·산림자원 개발 투자</td></tr>
                <tr><td>해외건설 기관전용 사모집합투자기구</td><td>해외건설촉진법</td><td>2016년</td><td>해외건설공사 등 투자</td><td>해외건설사업 투자와 금융 지원</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="wiki-section" id="market" data-search="관련 현황 시장 현황 LP GP 투자대상 감독당국 약정액 이행액 투자 회수">
          <p class="wiki-eyebrow">제3절</p>
          <h2>기관전용 사모집합투자기구 관련 현황</h2>
          <div class="wiki-subsection">
            <h3>시장 발전 단계</h3>
            <p class="wiki-paragraph">국내 기관전용 사모집합투자기구 산업은 준비기, 도약기를 거쳐 2012년부터 투자회수와 운용기간·운용능력 차별화가 진행되는 성장기에 진입한 것으로 제시됩니다.</p>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>단계</th><th>시기</th><th>시장 특징</th><th>실무상 의미</th></tr></thead>
              <tbody>
                <tr><td>준비기</td><td>제도 도입 초기</td><td>제도 활용 경험과 운용사 기반이 축적되는 단계</td><td>펀드 결성과 투자사례 형성이 중요했습니다.</td></tr>
                <tr><td>도약기</td><td>초기 성장 단계</td><td>기관투자자 참여와 자금모집 규모가 확대되는 단계</td><td>GP별 전략과 운용능력 차이가 나타나기 시작했습니다.</td></tr>
                <tr><td>성장기</td><td>2012년 이후</td><td>투자회수와 해산이 본격화되고 운용기간·성과 차별화가 진행되는 단계</td><td>LP는 단순 결성규모보다 회수성과와 사후관리 역량을 보게 됩니다.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection" id="market-scale">
            <h3>시장 규모</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>항목</th><th>2004년말</th><th>2022년말</th><th>증가</th><th>의미</th></tr></thead>
              <tbody>
                <tr><td>펀드 수</td><td>2개</td><td>1,098개</td><td>1,096개 증가</td><td>기관전용 사모집합투자기구가 독립된 대체투자 시장으로 성장했음을 보여줍니다.</td></tr>
                <tr><td>약정액</td><td>0.4조원</td><td>125.3조원</td><td>124.9조원 증가</td><td>LP가 펀드에 출자하기로 약속한 총 규모입니다.</td></tr>
                <tr><td>이행액</td><td>0.3조원</td><td>97.1조원</td><td>96.8조원 증가</td><td>약정 이후 실제 납입·집행된 자금 규모입니다.</td></tr>
              </tbody>
            </table>
            <p class="wiki-source-note">기준: 금융감독원 「기관전용 사모집합투자기구 실무안내」 제1장 제3절, 2022년 12월말 현황.</p>
          </div>
          <div class="wiki-subsection" id="gp-status">
            <h3>업무집행사원(GP) 현황</h3>
            <p class="wiki-paragraph">2022년 12월말 기준 기관전용 사모집합투자기구를 운용 중인 업무집행사원은 총 415사입니다. 성장기에는 투자실적 가시화와 운용능력 차별화가 진행되면서 전문운용사 위주의 산업으로 재편된 흐름이 나타납니다.</p>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>GP 유형</th><th>2005년</th><th>2007년</th><th>2008년</th><th>2011년</th><th>2012년</th><th>2022년</th></tr></thead>
              <tbody>
                <tr><td>전문운용사</td><td>7사<br>50.0%</td><td>17사<br>48.6%</td><td>23사<br>47.9%</td><td>58사<br>46.8%</td><td>69사<br>48.9%</td><td>312사<br>75.2%</td></tr>
                <tr><td>금융회사</td><td>7사<br>50.0%</td><td>13사<br>37.1%</td><td>17사<br>35.4%</td><td>44사<br>35.5%</td><td>46사<br>32.6%</td><td>46사<br>11.1%</td></tr>
                <tr><td>창투계 회사</td><td>-</td><td>5사<br>14.3%</td><td>8사<br>16.7%</td><td>22사<br>17.7%</td><td>26사<br>18.4%</td><td>57사<br>13.7%</td></tr>
                <tr><td>총계</td><td>14사</td><td>35사</td><td>48사</td><td>124사</td><td>141사</td><td>415사</td></tr>
              </tbody>
            </table>
            <p class="wiki-source-note">기준: 금융감독원 「기관전용 사모집합투자기구 실무안내」 제1장 제3절, 유형별 업무집행사원 현황.</p>
          </div>
          <div class="wiki-subsection">
            <h3>자금모집·투자·회수</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>항목</th><th>2022년말 기준</th><th>시장 흐름</th><th>서비스 데이터와의 연결</th></tr></thead>
              <tbody>
                <tr><td><button class="wiki-ref" type="button" data-ref="fund_raising">자금모집</button></td><td>약정액 125.3조원</td><td>연기금 등 기관투자자 기반 확대 후 누적 자금모집 규모가 100조원을 넘어섰습니다.</td><td>LP 출자공고, 위탁운용사 선정, 펀드 결성 기사와 연결</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="investment">투자</button></td><td>누적 투자규모 192.4조원</td><td>전문인력 보유 펀드는 전략적 투자, 금융회사 운용 펀드는 재무적 투자 성격이 강하게 나타납니다.</td><td>GP별 포트폴리오, M&A, 인수금융, 성장투자 뉴스와 연결</td></tr>
                <tr><td><button class="wiki-ref" type="button" data-ref="exit">회수</button></td><td>누적 회수금액 108.5조원</td><td>투자 회수와 해산이 본격화되면서 성과 검증 가능성이 확대됐습니다.</td><td>매각, IPO, 배당, 세컨더리 거래, 청산 데이터와 연결</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>시장 참여자 구조</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>구성</th><th>주요 기능</th><th>관찰해야 할 데이터</th></tr></thead>
              <tbody>
                <tr><td>LP</td><td>펀드 출자와 위탁운용사 선정</td><td>출자공고, 선정결과, 약정규모, 출자조건, 운용사 평가</td></tr>
                <tr><td>GP</td><td>펀드 결성, 투자집행, 사후관리, 회수</td><td>AUM, 펀드 히스토리, 투자전략, 핵심 인력, 포트폴리오, 회수성과</td></tr>
                <tr><td>투자대상회사</td><td>인수·투자·구조개선의 대상</td><td>산업, 재무상태, 지배구조, 거래조건, 인수 후 변화</td></tr>
                <tr><td>감독당국</td><td>등록, 보고, 검사, 제도개편</td><td>GP 등록, 변경보고, 검사 이슈, 법령·규정 개정</td></tr>
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
          <p class="wiki-eyebrow">제4절</p>
          <h2>연혁</h2>
          <div class="wiki-subsection">
            <h3>제도 변화 흐름</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>시점</th><th>법령·제도</th><th>주요 변화</th><th>의미</th></tr></thead>
              <tbody>
                <tr><td>2004년</td><td>간접투자자산 운용업법</td><td>합자회사 형태의 사모투자전문회사 제도 도입</td><td>국내 PEF 제도의 출발점</td></tr>
                <tr><td>2006년</td><td>시행령 개정</td><td>유한책임사원 최소 출자가액 완화, 자산운용 범위 확대, 의무투자비율 완화</td><td>출자자 기반과 운용 재량 확대</td></tr>
                <tr><td>2007년</td><td>해외투자 규제 정비</td><td>해외 회사 또는 SPC를 통한 해외자산 투자와 해외 부실채권 투자 허용</td><td>국내 PEF의 투자대상 확장</td></tr>
                <tr><td>2009년</td><td>자본시장법 체계 전환</td><td>투자목적회사 범위, 등록 공고, 여유자금 운용, 대기업집단 관련 규제 정비</td><td>PEF 규율체계가 자본시장법 안으로 편입</td></tr>
                <tr><td>2010년</td><td>기업재무안정 PEF 도입</td><td>재무구조개선기업 등에 대한 민간 자금 공급 통로 마련</td><td>위기·구조조정 자금 공급 기능 강화</td></tr>
                <tr><td>2013년</td><td>규제 선진화</td><td>GP 등록제, 보고의무, 유한책임사원의 운용 관여 제한 명확화</td><td>운용사 관리와 LP-GP 역할 구분 강화</td></tr>
                <tr><td>2015년</td><td>사모펀드 제도개편</td><td>적격투자자 범위, 업무집행사원 감독, 설립규제, 금융전업그룹 규제 합리화</td><td>사모펀드 시장 확대와 감독체계 정비</td></tr>
                <tr><td>2021년</td><td>일반 사모·기관전용 사모 체계 개편</td><td>전문투자형·경영참여형 구분을 투자자 범위 기준 체계로 재편</td><td>기관전용 사모펀드의 운용범위 확대와 투자자 보호 강화</td></tr>
              </tbody>
            </table>
          </div>
          <div class="wiki-subsection">
            <h3>2021년 사모펀드 체계개편 주요 내용</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>주제</th><th>주요 내용</th></tr></thead>
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
          <div class="wiki-subsection" id="reform-2021">
            <h3>개편 전후 실무 포인트</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>항목</th><th>개편 전 실무상 초점</th><th>개편 후 실무상 초점</th></tr></thead>
              <tbody>
                <tr><td>펀드 구분</td><td>전문투자형과 경영참여형을 운용목적 중심으로 구분</td><td>일반 사모펀드와 기관전용 사모펀드를 투자자 범위 중심으로 구분</td></tr>
                <tr><td>기관전용 운용</td><td>경영참여 목적 의무와 관련 제한이 핵심</td><td>기관투자자 중심 구조 안에서 일반 사모펀드와 유사한 운용규제 적용</td></tr>
                <tr><td>감독 포인트</td><td>설립·운용 규제와 경영참여 요건 준수</td><td>GP 등록·보고·검사, 운용인력, 불건전행위 규율, 투자자 보호 장치 강화</td></tr>
                <tr><td>서비스 연결</td><td>법령 변화와 펀드 결성 기사 중심 관찰</td><td>LP 출자조건, GP 등록·제재, 투자전략 변화, 회수성과 데이터까지 연결 필요</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="wiki-section" id="rules" data-search="법령 규정 감독 보고 설립 변경 해산 특수목적">
          <p class="wiki-eyebrow">참조</p>
          <h2>법령·규정 참조</h2>
          <div class="wiki-subsection" id="law-map">
            <h3>주요 법령 조항 매핑</h3>
            <table class="wiki-table wiki-wide-table">
              <thead><tr><th>주제</th><th>주요 근거</th><th>위키에서 연결되는 내용</th><th>실무 확인 포인트</th></tr></thead>
              <tbody>
                <tr><td>정의</td><td>자본시장법 제9조</td><td><a href="#legal-definition">기관전용 사모집합투자기구 정의</a></td><td>사모집합투자기구, 기관전용, 일반 사모 구분</td></tr>
                <tr><td>기관전용 사모 특례</td><td>자본시장법 제249조의11 이하</td><td><a href="#classification">개요 및 분류</a></td><td>GP·LP 구조, 투자자 범위, 운용 관련 특례</td></tr>
                <tr><td>차입·재무보증</td><td>자본시장법 및 시행령상 운용규제</td><td><button class="wiki-ref" type="button" data-ref="leverage">차입·재무보증</button></td><td>펀드와 투자목적회사 합산 한도, 거래 실질 기준</td></tr>
                <tr><td>금전대여</td><td>사모펀드 운용규제 개편 사항</td><td><button class="wiki-ref" type="button" data-ref="money_lending">금전대여 운용</button></td><td>차주, 업종 제한, 투자전략 문서화</td></tr>
                <tr><td>보고·감독</td><td>금융감독원 보고·검사 체계</td><td><button class="wiki-ref" type="button" data-ref="fss_reporting">설립·변경·해산 보고</button></td><td>설립보고, 변경보고, 해산·청산 보고 일정</td></tr>
              </tbody>
            </table>
          </div>
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

        <section class="wiki-section" id="sources" data-search="문서 기준 kvca kdi 금융감독원 실무안내">
          <p class="wiki-eyebrow">기준 문서</p>
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
    return """    <nav class="wiki-top-nav" aria-label="Wiki 내부 이동">
      <a class="active" href="#chapter">개관</a>
      <a href="#background">도입 배경</a>
      <a href="#classification">분류</a>
      <a href="#market">현황</a>
      <a href="#history">연혁</a>
      <a href="#rules">법령·규정</a>
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
      padding: 14px 0 16px;
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
      font-size: clamp(28px, 4vw, 44px);
      line-height: 1.08;
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
    .wiki-source-note {
      margin: 0;
      color: var(--wiki-tertiary);
      font-size: 12px;
      font-weight: 780;
      line-height: 1.55;
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
    .wiki-wide-table th:first-child,
    .wiki-wide-table td:first-child { width: 150px; }
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
    .wiki-ref-checklist {
      display: grid;
      gap: 6px;
      margin: 12px 0 0;
      padding-left: 18px;
      color: var(--wiki-secondary);
      font-size: 13px;
      line-height: 1.55;
    }
    .wiki-ref-checklist[hidden] { display: none; }
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
      .wiki-subsection { overflow-x: auto; }
      .wiki-table { min-width: 680px; }
      .wiki-table th,
      .wiki-table td {
        padding: 9px 0;
      }
      .wiki-table th:first-child,
      .wiki-table td:first-child {
        position: sticky;
        left: 0;
        z-index: 1;
        background: var(--wiki-bg);
      }
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
  const refSummary = document.getElementById("wikiRefSummary");
  const refChecklist = document.getElementById("wikiRefChecklist");
  const refRelated = document.getElementById("wikiRefRelated");
  const refSource = document.getElementById("wikiRefSource");
  const closeButton = panel?.querySelector(".wiki-ref-close");
  const search = document.getElementById("wikiSearch");
  const searchStatus = document.getElementById("wikiSearchStatus");
  const sections = Array.from(document.querySelectorAll(".wiki-section"));
  const topLinks = Array.from(document.querySelectorAll(".wiki-top-nav a"));

  const openRef = (key) => {
    const item = refs[key];
    if (!item || !panel) return;
    refType.textContent = item.type || "참조";
    refTitle.textContent = item.label || key;
    refLocation.textContent = item.location ? `위치: ${item.location}` : "";
    refSummary.textContent = item.summary || "";
    refSummary.hidden = !item.summary;
    refChecklist.replaceChildren();
    (item.checkpoints || []).forEach((checkpoint) => {
      const li = document.createElement("li");
      li.textContent = checkpoint;
      refChecklist.append(li);
    });
    refChecklist.hidden = !refChecklist.childElementCount;
    refSource.textContent = item.source_label ? `${item.source_label} 열기` : "자료 열기";
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
