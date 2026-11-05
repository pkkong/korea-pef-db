"""Select offering evidence without changing archived byte-extraction proofs."""
import re


def is_submission_form_v2(name):
    # Some issuers label every file '(공고)', including blank proposal forms.
    title = re.sub(r'^\s*[\[(]\s*공고\s*[\])]\s*', '', name)
    if re.search(r'제안(?:서)?\s*요청서|공고|모집|선정계획', title):
        return False
    return bool(re.search(r'양식|서식|제안서|제출서류|체크리스트|\.xlsx?$', title, re.I))


def is_submission_form(name):
    # Reused recruitment titles (including 재공고) do not make a terminal
    # submission-template label offering evidence. Keep ambiguous PDFs/bundles.
    terminal_template = re.search(
        r'(?:제출\s*서류|제안\s*(?:서류|서))\s*(?:및|[·ㆍ&+])\s*'
        r'(?:서식|양식)\s*(?:[（(]\s*(?:한글|엑셀|word)\s*'
        r'(?:서식|양식)?\s*[)）])?\s*\.(?:hwp|hwpx|xlsx?|docx?)\s*$',
        name, re.I,
    )
    return bool(terminal_template) or is_submission_form_v2(name)


def is_submission_text(text):
    # A proposal template can be labelled RFP; its title still identifies it.
    first=next((line.strip() for line in text.splitlines() if line.strip()), '')
    return bool(re.fullmatch(r'.{0,80}(?:제안서|신청서)\s*(?:양식|서식)', first))


def is_submission_attachment(notice, url):
    names = [a.get('name', '') for a in notice.get('attachments', [])
             if isinstance(a, dict) and a.get('url') == url]
    return (any(is_submission_form(name) for name in names)
            or is_submission_text(notice.get('attachment_texts', {}).get(url, '')))
