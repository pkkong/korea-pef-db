#!/usr/bin/env python
"""Send the latest daily news clipping by email and/or Telegram."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from daily_news_common import DEFAULT_ENV, load_env_file


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKDOWN = REPO_ROOT / "exports" / "daily_news" / "daily_news_brief_latest.md"
DEFAULT_HTML = REPO_ROOT / "exports" / "daily_news" / "daily_news_brief_latest.html"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the daily PEF news clipping")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--subject", default="Daily PEF News Clipping")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_env_file(args.env)

    markdown_text = args.markdown.read_text(encoding="utf-8")
    html_text = args.html.read_text(encoding="utf-8") if args.html.exists() else ""

    sent_channels: list[str] = []
    if send_email_enabled():
        if args.dry_run:
            print("DRY-RUN email enabled")
        else:
            send_email(args.subject, markdown_text, html_text)
        sent_channels.append("email")

    if send_telegram_enabled():
        if args.dry_run:
            print("DRY-RUN telegram enabled")
        else:
            send_telegram(markdown_text)
        sent_channels.append("telegram")

    if not sent_channels:
        print("No delivery channel configured. Set SMTP_* or TELEGRAM_* environment variables.")
        return 0

    print("Sent daily news clipping via " + ", ".join(sent_channels))
    return 0


def send_email_enabled() -> bool:
    required = ["SMTP_HOST", "SMTP_FROM", "SMTP_TO"]
    return all(os.environ.get(name, "").strip() for name in required)


def send_email(subject: str, markdown_text: str, html_text: str) -> None:
    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ["SMTP_FROM"].strip()
    recipients = [value.strip() for value in os.environ["SMTP_TO"].split(",") if value.strip()]

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(markdown_text, "plain", "utf-8"))
    if html_text:
        message.attach(MIMEText(html_text, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        if username and password:
            smtp.login(username, password)
        smtp.sendmail(sender, recipients, message.as_string())


def send_telegram_enabled() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def send_telegram(markdown_text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    chunks = split_telegram_message(markdown_text)
    for chunk in chunks:
        payload = urlencode(
            {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": "false",
            }
        ).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"Telegram send failed: {body}")


def split_telegram_message(text: str, max_len: int = 3800) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > max_len:
            parts.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        parts.append("\n".join(current))
    return parts or [text[:max_len]]


if __name__ == "__main__":
    raise SystemExit(main())
