"""Curated public logo assets for compact circular brand marks.

The public UI uses small circular slots for publishers, LPs, and GPs. Prefer a
compact official CI or high-resolution official touch icon when available, then
fall back to Google S2 favicons only for broad coverage.
"""

from __future__ import annotations

from urllib.parse import urlparse


BRAND_MARKS: dict[str, dict[str, str]] = {
    # News publishers
    "hankyung.com": {
        "logo_url": "https://hkstatic.hankyung.com/resource/common/img/logo/logo-hk-short-w.svg",
        "background": "#17376f",
        "border": "#17376f",
        "image_width": "30px",
        "image_height": "18px",
    },
    "marketinsight.hankyung.com": {
        "logo_url": "https://hkstatic.hankyung.com/resource/common/img/logo/logo-hk-short-w.svg",
        "background": "#17376f",
        "border": "#17376f",
        "image_width": "30px",
        "image_height": "18px",
    },
    "mk.co.kr": {
        "logo_url": "https://static.mk.co.kr/favicon_180180.png",
    },
    "dealsite.co.kr": {
        "logo_url": "https://dealsite.co.kr/static/images/favicon.svg",
    },
    "etoday.co.kr": {
        "logo_url": "https://www.etoday.co.kr/images/etoday_logo_pc.png",
        "image_width": "31px",
        "image_height": "15px",
    },
    "investchosun.com": {
        "logo_url": "https://img.investchosun.com/images/2025/logo_header.svg",
        "image_width": "32px",
        "image_height": "13px",
    },
    "thebell.co.kr": {
        "logo_url": "https://image.thebell.co.kr/thebell10/img/2020/top-logo.png",
        "image_width": "31px",
        "image_height": "17px",
    },
    "naver.com": {
        "logo_url": "https://www.naver.com/favicon.ico",
        "background": "#03c75a",
        "border": "#03c75a",
    },
    # Platform/company marks commonly surfaced in deal/news contexts.
    "thevc.kr": {
        "background": "#111827",
        "border": "#111827",
    },
    # GP/LP directory
    "mbkpartners.com": {
        "logo_url": "https://www.mbkpartners.com/mbk/images/common/og_image.png",
        "background": "#183f7a",
        "border": "#183f7a",
    },
    "mbkpartnerslp.com": {
        "logo_url": "https://www.mbkpartners.com/mbk/images/common/og_image.png",
        "background": "#183f7a",
        "border": "#183f7a",
    },
    "hcompany.com": {
        "logo_url": "https://www.hcompany.com/assets/img/icon/favicon.png",
        "background": "#111111",
        "border": "#111111",
    },
    "immholdings.co.kr": {
        "logo_url": "https://imminvestment.com/imm/wp-content/uploads/2017/01/favicon.png",
        "background": "#6fca55",
        "border": "#6fca55",
    },
    "imminvestment.com": {
        "logo_url": "https://imminvestment.com/imm/wp-content/uploads/2017/01/favicon.png",
        "background": "#6fca55",
        "border": "#6fca55",
    },
    "kvic.or.kr": {
    },
    "fund.nps.or.kr": {
        "logo_url": "https://www.nps.or.kr/images/contents/ci_logo2.png",
        "image_width": "32px",
        "image_height": "18px",
    },
    "nps.or.kr": {
        "logo_url": "https://www.nps.or.kr/images/contents/ci_logo2.png",
        "image_width": "32px",
        "image_height": "18px",
    },
    "kdb.co.kr": {
        "logo_url": "https://www.kdb.co.kr/wcmscontents/hmp/ch/bi/bi/rc/img_symbol_chbi.png",
    },
    "kgrowth.or.kr": {
        "logo_url": "https://www.kgrowth.or.kr/favicon.ico",
    },
    "apfs.kr": {
        "logo_url": "https://www.apfs.kr/images/common/kr.ico",
    },
    "koreapost.go.kr": {
        "logo_url": "https://www.koreapost.go.kr/site/kpost/images/bg/cymbol_mark.png",
        "image_width": "32px",
        "image_height": "18px",
    },
    "ktcu.or.kr": {
        "logo_url": "https://www.ktcu.or.kr/humanframe/theme/pc/assets/images/common/favicon.ico",
    },
    "cu.co.kr": {
        "logo_url": "https://www.cu.co.kr/images/web/cu/layout/logo60.png",
    },
    "stic.co.kr": {
        "logo_url": "https://www.stic.co.kr/img/com/stic_logo.png",
        "image_width": "31px",
        "image_height": "16px",
    },
}


PUBLISHER_DOMAINS: dict[str, str] = {
    "한국경제": "hankyung.com",
    "매일경제": "mk.co.kr",
    "딜사이트": "dealsite.co.kr",
    "더벨": "thebell.co.kr",
    "인베스트조선": "investchosun.com",
    "이투데이": "etoday.co.kr",
    "조선비즈": "biz.chosun.com",
    "아시아경제": "view.asiae.co.kr",
    "서울경제": "sedaily.com",
    "이데일리": "edaily.co.kr",
    "연합인포맥스": "news.einfomax.co.kr",
    "뉴스톱": "newstopkorea.com",
    "블로터": "bloter.net",
    "헤럴드경제": "biz.heraldcorp.com",
}


def normalized_domain(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    domain = (parsed.hostname or raw).lower().strip()
    return domain.removeprefix("www.")


def domain_from_url(url: object) -> str:
    return normalized_domain(url)


def publisher_domain(label: object) -> str:
    return PUBLISHER_DOMAINS.get(str(label or "").strip(), "")


def brand_key_for_domain(domain: object) -> str:
    normalized = normalized_domain(domain)
    if not normalized:
        return ""
    for suffix in sorted(BRAND_MARKS, key=len, reverse=True):
        if normalized == suffix or normalized.endswith(f".{suffix}"):
            return suffix
    return ""


def preferred_domain(url: object, label: object = "") -> str:
    domain = normalized_domain(url)
    label_domain = publisher_domain(label)
    if label_domain and (not domain or domain == "news.google.com"):
        return label_domain
    return domain or label_domain


def google_favicon_url(domain: object) -> str:
    normalized = normalized_domain(domain)
    if not normalized:
        return ""
    return f"https://www.google.com/s2/favicons?domain={normalized}&sz=64"


def brand_logo_url(url: object, label: object = "") -> str:
    domain = preferred_domain(url, label)
    key = brand_key_for_domain(domain)
    if key:
        logo_url = BRAND_MARKS[key].get("logo_url", "")
        if logo_url:
            return logo_url
    return google_favicon_url(domain)


def brand_style_string(url: object = "", label: object = "") -> str:
    domain = preferred_domain(url, label)
    key = brand_key_for_domain(domain)
    if not key:
        return ""
    mark = BRAND_MARKS[key]
    background = mark.get("background", "")
    border = mark.get("border", background)
    parts = []
    if background:
        parts.append(f"--logo-bg: {background};")
    if border:
        parts.append(f"--logo-border: {border};")
    image_width = mark.get("image_width", "")
    image_height = mark.get("image_height", "")
    if image_width:
        parts.append(f"--logo-img-width: {image_width};")
    if image_height:
        parts.append(f"--logo-img-height: {image_height};")
    return " ".join(parts)


def brand_style_attr(url: object = "", label: object = "") -> str:
    style = brand_style_string(url, label)
    return f' style="{style}"' if style else ""
