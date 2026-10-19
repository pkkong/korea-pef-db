"""Resolve legacy published GP navigation without depending on sibling services."""
from __future__ import annotations

import html
import os
import re
from urllib.parse import urlsplit, urlunsplit

_ANCHOR = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_HREF = re.compile(r"(?P<prefix>\bhref\s*=\s*)(?P<quote>[\"'])(?P<url>.*?)(?P=quote)", re.IGNORECASE | re.DOTALL)
_ASSET_TAG = re.compile(r"<(?:link|script)\b[^>]*>", re.IGNORECASE)
_ASSET_URL = re.compile(r"(?P<prefix>\b(?:href|src)\s*=\s*)(?P<quote>[\"'])(?P<url>.*?)(?P=quote)", re.IGNORECASE | re.DOTALL)
_LOCAL_ASSETS = {"assets/service.css", "static/service.css", "assets/service.js", "apple-touch-icon.png", "favicon.ico", "site.webmanifest"}
_GP_PAGE = re.compile(r"(?:gps|market|gp-\d+|person-\d+)\.html")
_DEFAULT_NEWSLETTER = "https://kpef-newsletter.vercel.app"
_DEFAULT_LP = "https://kpef-lp.vercel.app"
_DEFAULT_GP = "https://kpef-gp.vercel.app"


def _public_url(name: str, fallback: str) -> str:
    value = os.environ.get(name, fallback).rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        return fallback
    return value


def rewrite_gp_navigation(page_html: str) -> str:
    """Rewrite only known service routes; evidence and source URLs stay intact.

    Call this after checking the stored HTML hash, never before verification.
    """
    newsletter = _public_url("NEWSLETTER_PUBLIC_URL", _DEFAULT_NEWSLETTER)
    lp = _public_url("LP_PUBLIC_URL", _DEFAULT_LP)
    gp = _public_url("GP_PUBLIC_URL", _DEFAULT_GP)
    owned = {urlsplit(base).netloc.lower() for base in (newsletter, lp, gp, _DEFAULT_NEWSLETTER, _DEFAULT_LP, _DEFAULT_GP)}

    def replace_href(match: re.Match[str]) -> str:
        original = html.unescape(match.group("url"))
        parts = urlsplit(original)
        path = parts.path
        if not path or original.startswith("#"):
            return match.group(0)
        if parts.scheme or parts.netloc:
            if parts.scheme not in {"", "https", "http"}:
                return match.group(0)
            if parts.netloc.lower() == "pkkong.github.io":
                if not path.startswith("/kpef-newsletter/"):
                    return match.group(0)
                path = path[len("/kpef-newsletter/"):]
            elif parts.netloc.lower() in owned:
                path = path.lstrip("/")
            else:
                return match.group(0)
        else:
            path = path.removeprefix("./").lstrip("/")
        if path in {"index.html", "daily-news", "daily-news.html"}:
            target = newsletter + "/"
        elif path in {"lp-notices.html", "lp-notices", "samples/lp/index.html", "samples/lp/"}:
            target = lp + "/"
        elif _GP_PAGE.fullmatch(path):
            target = "/" + path
        else:
            return match.group(0)
        target_parts = urlsplit(target)
        target = urlunsplit((target_parts.scheme, target_parts.netloc, target_parts.path, parts.query, parts.fragment))
        quote = match.group("quote")
        return match.group("prefix") + quote + html.escape(target, quote=True) + quote

    def replace_asset(match: re.Match[str]) -> str:
        parts = urlsplit(html.unescape(match.group("url")))
        path = parts.path
        if parts.scheme or parts.netloc:
            if parts.scheme not in {"", "https", "http"}:
                return match.group(0)
            if parts.netloc.lower() == "pkkong.github.io":
                if not path.startswith("/kpef-newsletter/"):
                    return match.group(0)
                path = path[len("/kpef-newsletter/"):]
            elif parts.netloc.lower() in owned:
                path = path.lstrip("/")
            else:
                return match.group(0)
        else:
            path = path.removeprefix("./").lstrip("/")
        if path not in _LOCAL_ASSETS:
            return match.group(0)
        target = urlunsplit(("", "", "/" + path, parts.query, parts.fragment))
        quote = match.group("quote")
        return match.group("prefix") + quote + html.escape(target, quote=True) + quote

    page_html = _ANCHOR.sub(lambda tag: _HREF.sub(replace_href, tag.group(0)), page_html)
    return _ASSET_TAG.sub(lambda tag: _ASSET_URL.sub(replace_asset, tag.group(0)), page_html)
