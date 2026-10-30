"""Labelled KAMCO offering facts; caller must validate the complete receipt first."""
import base64
import hashlib
import re
from datetime import datetime
from urllib.parse import urlsplit


def _sources(n):
    if n.get('institution_id') != 'kamco':
        return []
    if re.search(r'PF사업장|부동산|대출형|프로젝트|\bVC\b|벤처펀드', n.get('title', ''), re.I):
        return []
    def official(url):
        p = urlsplit(url)
        return p.scheme == 'https' and p.netloc == 'www.kamco.or.kr'
    if not official(n.get('url', '')) or not re.fullmatch('[0-9a-f]{64}', n.get('sha256', '')):
        return []
    sources = []
    names = {a['url']: a.get('name', '') for a in n.get('attachments', [])}
    for url, text in n.get('attachment_texts', {}).items():
        sha = n.get('attachment_hashes', {}).get(url, '')
        if (url not in names or not official(url) or not re.fullmatch('[0-9a-f]{64}', sha)
                or not isinstance(text, str) or re.search('^(?:제안서|신청서|서식|양식)', names[url])):
            continue
        # Native-board receipts retain the actual file; reject tampered bindings.
        try:
            raw = base64.b64decode(n['attachment_bytes'][url], validate=True)
        except (KeyError, ValueError, TypeError):
            continue
        if hashlib.sha256(raw).hexdigest() != sha:
            continue
        # Full file/text replay is the publisher's validate_notice contract.
        text = re.split(r'(?m)^\s*\[붙임\s*[1-9]\d*\]|^\s*\[별첨\s*[1-9]\d*\]', text, maxsplit=1)[0]
        sources.append((url, text, sha))
    return sources


def _scope(text):
    t = re.sub(r'\s+', '', text)
    overview = re.search(r'선정계획개요(.*?)3[.]투자대상', t)
    if not overview or '운용사선정계획공고' not in t[:250]:
        return []
    o = overview[1]
    mode = re.search(r'운용방식[▪□:：-]*블라인드펀드선정방식', o)
    legal = re.search(r'출자대상투자기구.{0,65}기관전용사모집합투자기구[-▪]*창업[·ㆍ]벤처전문사모집합투자기구제외', o)
    domestic = re.search(r'아래기업에대한투자제한\(비주목적투자포함\)[-▪]*외국기업(?=[-▪])', t)
    if (not all((mode, legal, domestic)) or re.search(r'운용방식.{0,30}(?:프로젝트|대출형|VC)', o, re.I)
            or re.search(r'외국기업.{0,12}(?:허용|가능|제한없|제한하지)', t)):
        return []
    return [m[0] for m in (mode, legal, domestic)]


def pe_track(n):
    return [quote for _, text, _ in _sources(n) for quote in _scope(text)]


def terms(n):
    sources = [(u, t, h) for u, t, h in _sources(n) if _scope(t)]
    if not sources:
        raise ValueError('KAMCO domestic PE blind offering not verified')
    result = {'amount_scope': 'pe_only', 'extraction_evidence': {}}
    facts = {}
    def record(key, value, url, sha, quote):
        if key in facts and facts[key] != value:
            raise ValueError('Conflicting KAMCO offering ' + key)
        facts[key] = value
        result['extraction_evidence'].setdefault(key, []).append({'source_url': url, 'sha256': sha, 'quote': quote})
    for url, raw, sha in sources:
        text = re.sub(r'\s+', '', raw)
        result['extraction_evidence'].setdefault('pe_track', []).extend(
            {'source_url': url, 'sha256': sha, 'quote': q} for q in _scope(raw))
        for key, label, unit in [('total', '공사출자금액', '억원'), ('fund_target', '최소결성금액', '억원'),
                                  ('manager_count', '선정운용사', '개사')]:
            for m in re.finditer(label + r'[▪□:：-]*(\d[\d,]*)' + unit + r'(?!이내|이상|이하|내외|또는|~|∼)(?=[▪□※*\-가-힣]|\d+[.]|$)', text):
                value = int(m[1].replace(',', ''))
                if value <= 0:
                    raise ValueError('Invalid KAMCO offering quantity')
                record(key, value, url, sha, m[0])
        for m in re.finditer(r'접수일시[▪□ㅇ:：-]*(20\d{2})년(\d{1,2})월(\d{1,2})일(\d{1,2}):(\d{2})[∼~～](\d{1,2}):(\d{2})', text):
            y, mo, d, sh, sm, eh, em = map(int, m.groups())
            start, end = datetime(y, mo, d, sh, sm), datetime(y, mo, d, eh, em)
            if end <= start or end.date().isoformat() < n['date']:
                raise ValueError('Invalid KAMCO application range')
            record('deadline', end.isoformat() + '+09:00', url, sha, m[0])
        for m in re.finditer(r'선정결과발표[▪□:：-]*(20\d{2})년(\d{1,2})월(?:중)?\(예정\)', text):
            stamp = datetime(int(m[1]), int(m[2]), 1).strftime('%Y-%m')
            if stamp < n['date'][:7]:
                raise ValueError('KAMCO planned selection predates notice')
            record('schedule_selection', stamp, url, sha, m[0])
        purpose = re.search(r'□\s*주목적 투자대상 및 의무투자비율\s*(.*?)\n□', raw, re.S)
        if purpose and 0 < len(purpose[1]) < 2200:
            clauses = []
            percentages = {}
            for m in re.finditer(r'(?m)^\s*(?:\d+[.]\s*)?([^\n]*?약정총액의\s*(\d+(?:[.]\d+)?)%\s*이상\s*투자)\s*$', purpose[1]):
                percent = float(m[2])
                target = re.sub(r'\s+', '', m[1].split('약정총액의')[0])
                if not 0 < percent <= 100 or (target in percentages and percentages[target] != percent):
                    raise ValueError('Conflicting KAMCO investment obligation')
                percentages[target] = percent
                if m[1].strip() not in clauses:
                    clauses.append(m[1].strip())
            if clauses:
                record('primary_investment', '; '.join(clauses), url, sha, purpose[0].rstrip('□').strip())
    if 'total' in facts:
        result.update(commitment_amount_krw=facts['total'] * 100_000_000,
                      commitment_label=f"{facts['total']:,}억원")
    if 'manager_count' in facts:
        result.update(manager_count=facts['manager_count'], manager_count_label=f"{facts['manager_count']}개사")
    if facts.get('manager_count') == 1 and 'total' in facts:
        result['per_fund_amount_krw'] = result['commitment_amount_krw']
        result['extraction_evidence']['per_fund'] = result['extraction_evidence']['total'] + result['extraction_evidence']['manager_count']
    if 'fund_target' in facts:
        if facts.get('total', 0) > facts['fund_target']:
            raise ValueError('KAMCO commitment exceeds fund target')
        result['fund_target_label'] = f"{facts['fund_target']:,}억원"
    if 'deadline' in facts:
        result.update(deadline=facts['deadline'], deadline_precision='datetime')
    if 'primary_investment' in facts:
        result['primary_investment'] = {'text': facts['primary_investment'], 'source_url': result['extraction_evidence']['primary_investment'][0]['source_url']}
    if 'schedule_selection' in facts:
        stamp = facts['schedule_selection']
        result['schedule_stages'] = [{'stage': 'selection', 'label': '최종 선정', 'original_label': '선정결과발표',
            'date': stamp, 'date_label': f'{int(stamp[5:])}월', 'precision': 'month', 'status': 'planned',
            'source_url': n['url']}]
    return result
