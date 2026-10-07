"""Discover KDB-hosted originals for unresolved joint policy-bank notices."""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import time
from datetime import datetime
from urllib.error import URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

try:
    from .lp_notice_triage import assess_candidates, program_key, notice_stage
except ImportError:
    from lp_notice_triage import assess_candidates, program_key, notice_stage

BASE = "https://www.kdb.co.kr"
BOARD = BASE + "/CHBIPR23N00.act?_mnuId=IHIHIR0087"


def request(url, payload=None):
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "www.kdb.co.kr":
        raise ValueError("Unexpected KDB source")
    body = urlencode({"_JSON_": json.dumps(payload, ensure_ascii=False)}).encode() if payload else None
    req = Request(url, data=body, headers={"User-Agent": "Mozilla/5.0", "Referer": BOARD})
    for attempt in range(2):
        try:
            with urlopen(req, timeout=20) as response:
                if urlparse(response.geturl()).hostname != "www.kdb.co.kr":
                    raise ValueError("KDB redirected outside official host")
                return response.read()
        except (URLError, TimeoutError):
            if attempt == 1:
                raise
            time.sleep(1)


def detail_url(row):
    params = {"ITR_NAC_ID_MNG_SNO": row["ITR_NAC_ID_MNG_SNO"], "ITR_BLB_ID": "STD119",
              "NAC_SNO": "", "FIRST_MENU_ID": "CHBIPR23N00"}
    return BASE + "/BOUBUF02N00.act?" + urlencode({"_mnuId": "IHIHIR0087", "_PARAM_NAME": "NEXT_DATA",
                                                "_PARM_DATA": json.dumps(params, ensure_ascii=False, separators=(",", ":"))})


def _pdf_text(raw):
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)


def collect_related(candidates, notices, checked_at, fetch=request):
    result, holds = {}, []
    groups = {}
    for candidate in assess_candidates(candidates, notices):
        if not candidate["recruitment_url"] and candidate["stage"] in ("접수 결과", "1차 심사 결과", "선정 결과"):
            groups.setdefault(candidate["program_key"], candidate)
    for key, candidate in groups.items():
        try:
            title = candidate["title"].replace("『", "").replace("』", "").replace("「", "").replace("」", "")
            subject = re.match(r"(.*?펀드)", title)
            tokens = subject[1].split() if subject else []
            if len(tokens) < 2:
                raise ValueError("공동사업 검색어 미확인")
            # Search a distinctive strategy token, not a selected source ID or
            # full headline: official follow-ups sometimes misspell 펀드.
            keyword = tokens[-2]
            pages = 1
            for page in range(1, 4):
                payload = {"SEARCH_CONDITION": "NAC_CONE_TTL", "SEARCH_KEYWORD": keyword,
                           "SEARCH_CATEGORY": "", "ORDER_TYPE": "new", "MODE": "1,2,5,6", "ITR_BLB_ID": "STD119",
                           "HEADER_STD_WEB": {"REQ_PAGE_NO": page, "PAGE_ROW_COUNT": "50", "NEXT_PAGE_YN": "S",
                                              "NEXTPAGDTT": "P", "GRID_NEXTKEY_ITR_CND": ""}}
                response = json.loads(fetch(BASE + "/BOUBUF01R01.jct", payload))
                if response.get("COMMON_HEAD", {}).get("ERROR"):
                    raise ValueError("KDB board returned an error")
                pages = int(response["HEADER_STD_WEB"]["TOT_PAG_CNT"])
                for row in response["STDLIST_REC"]:
                    stamp = datetime.strptime(row["FST_ENR_DTM"], "%Y%m%d%H%M%S").date().isoformat()
                    normalized = row["NAC_CONE_TTL"].replace("편드", "펀드")
                    probe = {"institution_id": candidate["institution_id"], "date": stamp, "title": normalized}
                    if program_key(probe) != key:
                        continue
                    url = detail_url(row)
                    markup = fetch(url).decode("utf-8")
                    attachments = []
                    for m in re.finditer(r'<a\b[^>]*href="([^"]*fileView\?[^"]+)"[^>]*>(.*?)</a>', markup, re.S):
                        attachments.append({"url": urljoin(BASE, html.unescape(m[1])),
                                            "name": html.unescape(re.sub(r"<[^>]+>", "", m[2])).strip()})
                    document = {"institution_id": "kdb", "source_id": str(row["ITR_NAC_ID_MNG_SNO"]),
                                "url": url, "title": row["NAC_CONE_TTL"], "date": stamp,
                                "body": row["NAC_SMRY_CONE"], "modified_at": row["LST_CHG_DTM"],
                                "related_program_key": key, "attachments": attachments,
                                "attachment_hashes": {}, "attachment_texts": {}, "checked_at": checked_at}
                    document["sha256"] = hashlib.sha256(json.dumps([document["title"], stamp, document["body"]], ensure_ascii=False).encode()).hexdigest()
                    pdf = next((a for a in attachments if a["name"].lower().endswith(".pdf")), None)
                    if pdf:
                        raw = fetch(pdf["url"])
                        if not raw.startswith(b"%PDF"):
                            raise ValueError("KDB official attachment is not a PDF")
                        document["attachment_hashes"][pdf["url"]] = hashlib.sha256(raw).hexdigest()
                        document["attachment_texts"][pdf["url"]] = _pdf_text(raw)
                    result[url] = document
                if page >= pages:
                    break
            if pages > 3:
                raise ValueError("공동사업 검색 결과가 탐색 한도를 초과")
        except Exception as error:
            holds.append({"program_id": key, "reason": f"공동사업 원공고 수집 실패: {type(error).__name__}: {error}"})
    return list(result.values()), holds
