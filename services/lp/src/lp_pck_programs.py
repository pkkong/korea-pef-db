"""PCK's independently submitted PE track and source-bound recruitment rounds."""
import hashlib
import re
from datetime import datetime
from urllib.parse import urlsplit

try:
    from .lp_board_adapter_pck import canonical_notice
    from .lp_notice_triage import notice_stage
except ImportError:
    from lp_board_adapter_pck import canonical_notice
    from lp_notice_triage import notice_stage


def stage(n):
    value = notice_stage(n['title'])
    heading = re.sub(r'\s+', '', n['body'][:250])
    if value == '선정 결과' and '최종' not in n['title'] and re.search(r'위탁운용사1차(?:\(정량평가\))?선정결과', heading):
        return '1차 심사 결과'
    return value


def offering_sources(n):
    if n.get('institution_id') != 'pck_pension' or n.get('source_channel') != 'institution_board':
        return []
    if re.search(r'해외|글로벌|공동투자|프로젝트|사모대출|크레딧', n['title']):
        return []
    found = []
    for url, text in n.get('attachment_texts', {}).items():
        if (urlsplit(url).hostname != 'www.pension.or.kr'
                or not re.fullmatch('[0-9a-f]{64}', n.get('attachment_hashes', {}).get(url, ''))):
            continue
        # Ignore the appended templates and performance/AUM examples.
        head = re.split(r'4\s*\.\s*제안서\s*작성|<\s*별첨', text, maxsplit=1)[0]
        compact = re.sub(r'\s+', '', head)
        required = (r'선정유형대체투자\(PE,VC,Infra(?:,PD)?\)',
                    r'인프라에한해프로젝트형포함', r'\[블라인드형\]', r'기관전용사모집합투자기구',
                    r'복수자산군\(PE/VC/Infra(?:/PD)?\)에중복지원가능',
                    r'자산군별로제안서및제출서류일체를각각별도제출')
        if all(re.search(pattern, compact) for pattern in required):
            found.append((url, head, n['attachment_hashes'][url]))
    return found


def terms(n):
    sources = offering_sources(n)
    if not sources:
        return {}
    result = {'planned_schedule': [], 'extraction_evidence': {'pe_track': []}}
    deadlines, plans = set(), []
    for url, text, sha in sources:
        result['extraction_evidence']['pe_track'].append({'source_url': url, 'sha256': sha,
            'quote': '\n'.join(re.search(pattern, re.sub(r'\s+', '', text))[0] for pattern in
                (r'선정유형대체투자\(PE,VC,Infra(?:,PD)?\)', r'인프라에한해프로젝트형포함',
                 r'자산군별로제안서및제출서류일체를각각별도제출'))})
        year = re.search(r'(20\d{2})년도?\s*하반기', text[:400])
        if not year or year[1] != n['date'][:4]:
            continue  # Short dates require an explicit, consistent document year.
        schedule = re.search(r'선정\s*절차\s*및\s*일정(.*?)(?:※|펀드\s*만기)', text, re.S)
        if not schedule:
            continue
        for line in schedule[1].splitlines():
            m = re.fullmatch(r'\s*(\d{1,2})/(\d{1,2})\s*\([월화수목금토일]\)\s*(.+?)\s*', line)
            if not m:
                continue
            stamp = datetime(int(year[1]), int(m[1]), int(m[2])).date().isoformat()
            if stamp < n['date']:
                raise ValueError('PCK planned schedule precedes recruitment publication')
            label = re.sub(r'\s+', '', m[3])
            if re.search(r'접수마감|서류마감', label):
                time = re.search(r'\((\d{1,2}):(\d{2})\)', label)
                if time:
                    deadline = datetime.fromisoformat(stamp).replace(hour=int(time[1]), minute=int(time[2])).isoformat() + '+09:00'
                    deadlines.add(deadline)
                continue
            for phase, caption, pattern in (('screening','1차 심사',r'1차'), ('interview','2차 심사',r'2차'), ('selection','최종 선정',r'최종선정')):
                if re.search(pattern, label):
                    plans.append({'stage': phase, 'label': caption, 'original_label': m[3], 'date': stamp,
                                  'precision': 'date', 'status': 'planned', 'source_url': n['url']})
        # A separately labelled full date must agree with the schedule table.
        for m in re.finditer(r'접수마감\s*(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*\([월화수목금토일]\)\s*(\d{1,2}):(\d{2})', text):
            deadlines.add(datetime(*map(int,m.groups())).isoformat() + '+09:00')
    if len(deadlines) > 1:
        result['deadline_error'] = '공식 접수 마감이 서로 달라 확인 필요'
    elif deadlines:
        result.update(deadline=deadlines.pop(), deadline_precision='datetime')
        result['planned_schedule'] = plans
    # Overall mixed-asset budget and unspecified O개사 are intentionally absent.
    return result


def _canonical(url):
    try:
        return canonical_notice(url)
    except ValueError:
        return None


def groups(notices, existing):
    """Never attach a later call to an earlier result just because titles match."""
    canonical = {}
    for n in notices:
        url = _canonical(n['url'])
        if url and (url not in canonical or n.get('source_channel') == 'institution_board'):
            canonical[url] = {**n, 'url': url}
    notices = list(canonical.values())
    originals = {n['url']: n for n in notices if stage(n) == '모집 공고'}
    grouped = {url: [n] for url,n in originals.items()}
    holds = []
    for n in notices:
        if n['url'] in originals:
            continue
        targets = {u for u in n.get('related_notice_urls', []) if u in originals} if n.get('source_channel') == 'institution_board' else set()
        for p in existing:
            if p['institution_id'] != 'pck_pension' or not any(_canonical(e['url']) == n['url'] for e in p['events']):
                continue
            targets.update(_canonical(e['url']) for e in p['events'] if e['type'] == '모집 공고' and _canonical(e['url']) in originals)
        if len(targets) == 1:
            grouped[next(iter(targets))].append(n)
        else:
            holds.append({'stage': 'pck_stage_link', 'url': n['url'], 'reason': '모집 원공고 연결 근거가 없거나 복수 사업이 일치함'})
    return {'pck_pension:recruitment:' + hashlib.sha256(url.encode()).hexdigest()[:16]: members for url,members in grouped.items()}, holds
