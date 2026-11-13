"""Add an open LP program's application deadline to a reader's own calendar.

Both links are built at publication time from the stored deadline only: a Google
Calendar template URL and a one-event iCalendar file (RFC 5545) as a data: URI.
No feed, account or server route is involved.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from html import escape
from urllib.parse import quote, urlencode

LP_PUBLIC_URL = os.environ.get('LP_PUBLIC_URL', 'https://kpef-lp.vercel.app').rstrip('/')
KST = timezone(timedelta(hours=9))


def _text(value):
    """Escape TEXT values (RFC 5545 3.3.11)."""
    return (str(value).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n'))


def _fold(line):
    """Fold content lines at 75 octets without splitting a UTF-8 character."""
    out, current, size = [], '', 0
    for char in line:
        width = len(char.encode('utf-8'))
        if size + width > (75 if not out else 74):
            out.append(current)
            current, size = '', 0
        current += char
        size += width
    out.append(current)
    return '\r\n '.join(out)


def deadline_window(deadline):
    """(kind, start, end) for the event; a timed deadline is the hour before it."""
    value = str(deadline or '')
    if len(value) > 10 and 'T' in value:
        end = datetime.fromisoformat(value)
        if end.tzinfo is None:
            end = end.replace(tzinfo=KST)
        return 'datetime', end - timedelta(hours=1), end
    day = date.fromisoformat(value[:10])
    return 'date', day, day + timedelta(days=1)


def deadline_label(deadline):
    kind, _, end = deadline_window(deadline)
    if kind == 'datetime':
        local = end.astimezone(KST)
        return f'{local.month}월 {local.day}일 {local:%H:%M}'
    day = date.fromisoformat(str(deadline)[:10])
    return f'{day.month}월 {day.day}일'


def _stamp(value, kind):
    if kind == 'datetime':
        return value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return value.strftime('%Y%m%d')


def event_fields(p):
    title = p.get('public_title') or p['title']
    summary = f"[접수 마감] {p['institution_name']} · {title}"
    page = f"{LP_PUBLIC_URL}/program-{p['id']}.html"
    details = f"{p['institution_name']} 출자사업 접수 마감 {deadline_label(p['deadline'])}\n{page}"
    return summary, details, page


def google_calendar_url(p):
    kind, start, end = deadline_window(p['deadline'])
    summary, details, _ = event_fields(p)
    query = {'action': 'TEMPLATE', 'text': summary, 'dates': f'{_stamp(start, kind)}/{_stamp(end, kind)}',
             'details': details, 'ctz': 'Asia/Seoul'}
    return 'https://calendar.google.com/calendar/render?' + urlencode(query)


def ics_text(p, as_of):
    kind, start, end = deadline_window(p['deadline'])
    summary, details, page = event_fields(p)
    if kind == 'datetime':
        times = [f'DTSTART:{_stamp(start, kind)}', f'DTEND:{_stamp(end, kind)}']
    else:
        times = [f'DTSTART;VALUE=DATE:{_stamp(start, kind)}', f'DTEND;VALUE=DATE:{_stamp(end, kind)}']
    stamp = str(as_of)[:10].replace('-', '') + 'T000000Z'
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Korea PEF DB//LP deadlines//KO', 'CALSCALE:GREGORIAN',
             'METHOD:PUBLISH', 'BEGIN:VEVENT', f"UID:lp-deadline-{p['id']}@kpef-lp", f'DTSTAMP:{stamp}', *times,
             f'SUMMARY:{_text(summary)}', f'DESCRIPTION:{_text(details)}', f'URL:{page}',
             'BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{_text(summary)}', 'TRIGGER:-P1D', 'END:VALARM',
             'END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'


def deadline_calendar_block(p, as_of):
    """Links for a program still taking applications; '' otherwise.

    The block carries its deadline date so the page script hides it once the
    deadline has passed, even before the next publication.
    """
    if p.get('status') != '접수 중' or not p.get('deadline'):
        return ''
    day = str(p['deadline'])[:10]
    if day < str(as_of)[:10]:
        return ''
    data_uri = 'data:text/calendar;charset=utf-8,' + quote(ics_text(p, as_of))
    return (f'<div class="deadline-calendar" data-lp-calendar-until="{escape(day)}">'
            f'<span>접수 마감 {escape(deadline_label(p["deadline"]))}</span>'
            f'<a href="{escape(google_calendar_url(p))}" target="_blank" rel="noopener noreferrer">Google 캘린더에 추가</a>'
            f'<a href="{escape(data_uri)}" download="lp-deadline-{escape(p["id"])}.ics">캘린더 파일(.ics)</a></div>')
