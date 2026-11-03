"""Select offering evidence without changing archived byte-extraction proofs."""
import re


def is_submission_form(name):
    # Some issuers label every file '(공고)', including blank proposal forms.
    title = re.sub(r'^\s*[\[(]\s*공고\s*[\])]\s*', '', name)
    if re.search(r'제안(?:서)?\s*요청서|공고|모집|선정계획', title):
        return False
    return bool(re.search(r'양식|서식|제안서|제출서류|체크리스트|\.xlsx?$', title, re.I))


def is_submission_attachment(notice, url):
    names = [a.get('name', '') for a in notice.get('attachments', [])
             if isinstance(a, dict) and a.get('url') == url]
    return any(is_submission_form(name) for name in names)
