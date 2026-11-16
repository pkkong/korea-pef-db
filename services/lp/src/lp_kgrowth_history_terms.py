"""Offline review of retained Korea Growth 2020–2022 notice text.

This is deliberately not a public-program adapter or source validator. The review
bundle has listing HTML and parsed body/attachment text. The original 162-row
bundle omits detail bytes; attachment bytes are in a separate workflow artifact.
Matching stored metadata cannot replace replaying those originals. The companion
lp_kgrowth_history_replay module reports that distinct evidence check.

The first supported offering layouts are the explicitly separated PEF/PDF tables
observed in 2020/2021. Other legal-form mixtures stay held. Names are read only
from a matching final result's labelled PEF sections, with planned fund counts
checked separately from the number of managers in a Co-GP team.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from urllib.parse import parse_qs, urlsplit

try:
    from .kgrowth_listing import parse_listing, source_id
    from .lp_notice_triage import notice_stage
except ImportError:
    from kgrowth_listing import parse_listing, source_id
    from lp_notice_triage import notice_stage

KIND = 'lp_kgrowth_history_review_v1'
_HASH = re.compile(r'[a-f0-9]{64}')
_NUMBER = r'(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)'
_WINDOW = ('2020-01-01', '2022-12-31')
_TABLE = ('리그모펀드출자총액선정운용사수운용사별배정금액'
          '펀드별최소결성금액모펀드출자비율')


def _compact(text):
    return re.sub(r'\s|\u200b', '', unicodedata.normalize('NFKC', text))


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _source_quote(raw, normalized):
    """Map the whitespace-free table match back to the retained document text."""
    chars, positions = [], []
    for i, char in enumerate(raw):
        for value in unicodedata.normalize('NFKC', char):
            if not value.isspace() and value != '\u200b':
                chars.append(value)
                positions.append(i)
    start = ''.join(chars).find(normalized)
    if start < 0:
        raise ValueError('모집 표 인용문과 보관 판독문 불일치')
    return raw[positions[start]:positions[start + len(normalized) - 1] + 1]


def _money(token):
    if not re.fullmatch(_NUMBER, token):
        raise ValueError('출자금액 숫자 표기 미확인')
    return int(token.replace(',', '')) * 100_000_000


def _identity(notice):
    """Exact quoted fund identity, title year and explicit round; no fuzzy join."""
    title = unicodedata.normalize('NFKC', notice['title'])
    found = list(re.finditer(r'[「『]([^」』]+)[」』]', title))
    if len(found) != 1:
        raise ValueError('단일 펀드명 인용 제목 미확인')
    fund = found[0][1]
    years = set(re.findall(r'20\d{2}', title))
    if len(years) > 1:
        raise ValueError('제목의 사업 연도 충돌')
    year = next(iter(years), notice['date'][:4])
    if year < '2020' or year > '2022':
        raise ValueError('검토 대상 사업 연도 밖')
    fund = re.sub(r'20\d{2}년?도?', '', fund)
    tail = title[found[0].end():]
    # A screening's "1차 심사" is a stage, not a new round of the fund.
    tail = re.sub(r'\d+차\s*심사', '', tail)
    tail = re.split(r'위탁운용사|출자사업|제출서류|제안서|선정계획', tail, maxsplit=1)[0]
    rounds = re.findall(r'(?:제?\d+차(?:년도)?|정시(?:사업)?|수시(?:사업)?|앵커출자|매칭출자)', tail)
    return {'fund': _compact(fund), 'year': year, 'round': '/'.join(_compact(r) for r in rounds)}


def _check_metadata(bundle):
    """Check retained text metadata only. Never labels it raw-source validation."""
    if bundle.get('kind') != 'lp_institution_history_v1' or bundle.get('institution_id') != 'kgrowth':
        raise ValueError('성장금융 과거 검토 묶음 아님')
    if len(bundle.get('notices', [])) > 400 or len(bundle.get('listing_receipts', {})) > 1500:
        raise ValueError('과거 검토 묶음 크기 초과')
    receipts = bundle.get('listing_receipts', {})
    parsed = {}
    for digest, receipt in receipts.items():
        p = urlsplit(receipt['url'])
        q = parse_qs(p.query)
        if (p.scheme != 'https' or p.hostname != 'www.kgrowth.or.kr' or p.path != '/notice.asp'
                or p.username or p.password or p.fragment or p.port not in {None, 443}
                or q.get('str_type') != ['1'] or q.get('tab') != ['1']
                or digest != receipt.get('sha256') or _digest(receipt['html']) != digest):
            raise ValueError('보관 목록 주소 또는 지문 불일치')
        parsed[digest] = parse_listing(receipt['html'], receipt['url'])
    errors, notices, seen = [], [], set()
    for n in bundle.get('notices', []):
        try:
            ident = source_id(n['url'])
            if (n.get('institution_id') != 'kgrowth' or n.get('source_channel') != 'institution_board'
                    or ident != n['source_id'] or ident in seen):
                raise ValueError('보관 원문 기관 또는 식별자 충돌')
            date.fromisoformat(n['date'])
            if not _WINDOW[0] <= n['date'] <= _WINDOW[1]:
                raise ValueError('검토 대상 게시일 밖')
            proof = n.get('discovery_provenance', {})
            listing = proof.get('listing', {})
            receipt = receipts.get(listing.get('sha256'), {})
            if (proof.get('kind') != 'kgrowth_history_2020_v1' or not receipt
                    or listing.get('url') != receipt.get('url')
                    or not _HASH.fullmatch(proof.get('detail_sha256', ''))):
                raise ValueError('보관 목록 연결 또는 상세 지문 누락')
            rows = parsed[listing['sha256']]
            if not any(r['source_id'] == ident and r['date'] == n['date']
                       and _compact(r['title']) == _compact(n['title']) for r in rows):
                raise ValueError('보관 원문이 목록의 제목·게시일과 다름')
            body_digest = _digest(json.dumps([n['title'], n['date'], n['body']], ensure_ascii=False))
            if not n['body'].strip() or body_digest != n.get('sha256'):
                raise ValueError('보관 본문 지문 불일치')
            files = n.get('attachments', [])
            hashes, texts = n.get('attachment_hashes', {}), n.get('attachment_texts', {})
            if not set(texts) <= set(hashes) <= set(files):
                raise ValueError('보관 첨부 판독문·지문·관측 주소 불일치')
            for url, sha in hashes.items():
                p = urlsplit(url)
                if (p.scheme != 'https' or p.hostname != 'www.kgrowth.or.kr'
                        or p.path != '/down_file.asp' or p.username or p.password or p.fragment
                        or p.port not in {None, 443} or parse_qs(p.query).get('idx') != [ident]
                        or not _HASH.fullmatch(sha)):
                    raise ValueError('보관 첨부 원문 식별자 또는 지문 불일치')
            seen.add(ident)
            notices.append(n)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append({'url': n.get('url'), 'reason': str(exc)})
    return notices, errors


def _evidence(n, quote, attachment=None):
    value = {'source_url': n['url'], 'sha256': n['sha256'], 'quote': quote}
    if attachment:
        value.update(attachment_url=attachment, attachment_sha256=n['attachment_hashes'][attachment])
    return value


def _amount_count_options(prefix):
    """Collapsed HWP cells can join amount and count; require one reconciled read."""
    values = []
    for i in range(1, len(prefix)):
        amount, count = prefix[:i], prefix[i:]
        if re.fullmatch(_NUMBER, amount) and re.fullmatch(r'[1-9]\d?', count):
            values.append((_money(amount), int(count)))
    return values


def _three_track_table(text):
    start = text.find('1-1.블라인드,모펀드제안방식')
    end = text.find('1-2.프로젝트,운용사제안방식')
    if start < 0 or end <= start or text.count(_TABLE) != 1:
        return None
    section = text[start:end]
    table = re.search(re.escape(_TABLE) + r'PEF(.+?)PDF(.+?)PEF\(루키\)(.+?)소계(.+?)\(단위:억원\)', section)
    if not table:
        raise ValueError('블라인드 PEF/PDF/루키 표 양식 미확인')
    rows = []
    for block in table.groups()[:3]:
        hit = re.match(r'(.+?)개이내', block)
        if not hit:
            raise ValueError('리그별 출자금액·펀드 수 미확인')
        rows.append(_amount_count_options(hit[1]))
    total_match = re.fullmatch(r'(.+?)개이내총' + _NUMBER, table[4])
    if not total_match:
        raise ValueError('블라인드 합계 표 미확인')
    stated = re.search(r'총([1-9]\d*)개사이내에대하여(' + _NUMBER + r')억원배정', section)
    if not stated:
        raise ValueError('블라인드 총계 문장 미확인')
    totals = _amount_count_options(total_match[1])
    expected = (_money(stated[2]), int(stated[1]))
    solutions = [combo for combo in itertools.product(*rows)
                 if (sum(r[0] for r in combo), sum(r[1] for r in combo)) == expected
                 and expected in totals]
    if len(solutions) != 1:
        raise ValueError('리그별 금액·펀드 수와 합계 불일치 또는 복수 판독')
    pef, pdf, rookie = solutions[0]
    return {'layout': 'blind_pef_pdf_rookie', 'tracks': [
        {'label': 'PEF', 'amount_krw': pef[0], 'planned_fund_count': pef[1]},
        {'label': 'PEF(루키)', 'amount_krw': rookie[0], 'planned_fund_count': rookie[1]}],
        'excluded_tracks': [{'label': 'PDF', 'amount_krw': pdf[0], 'planned_fund_count': pdf[1]}],
        'evidence_quote': section[:table.end()]}


def _two_track_table(text):
    head = '항목블라인드펀드프로젝트펀드PEFPDF위탁운용금액'
    if text.count(head) != 1:
        return None
    section = text.split(head, 1)[1]
    budget = section.split('선정운용사수', 1)
    if len(budget) != 2:
        raise ValueError('블라인드/프로젝트 표 예산 행 미확인')
    amounts = re.findall(r'◦총(' + _NUMBER + r')억원이내', budget[0])
    count = re.match(r'◦([1-9]\d?)개사이내:제안펀드별', budget[1])
    if len(amounts) != 3 or not count:
        raise ValueError('블라인드 PEF 예산·펀드 수 미확인')
    return {'layout': 'blind_project_pef_pdf', 'tracks': [
        {'label': 'PEF', 'amount_krw': _money(amounts[0]), 'planned_fund_count': int(count[1]),
         'fund_count_basis': '이내'}], 'excluded_tracks': [{'label': 'PDF'}, {'label': '프로젝트'}],
        'evidence_quote': head + budget[0] + '선정운용사수' + budget[1][:count.end()]}


def _offering(n):
    readings = []
    for url, raw in n.get('attachment_texts', {}).items():
        text = _compact(raw)
        if not re.search(r'선정계획(?:을아래와같이)?공고|선정계획공고', text[:350]):
            continue
        parsed = _three_track_table(text) or _two_track_table(text)
        if parsed:
            identity = _identity(n)
            years = set(re.findall(r'(20\d{2})년', text[:350]))
            if identity['fund'] not in text[:350] or years and years != {identity['year']}:
                raise ValueError('모집 첨부의 펀드명·연도가 게시물과 다름')
            quote = _source_quote(raw, parsed.pop('evidence_quote'))
            parsed['evidence'] = _evidence(n, quote, url)
            parsed['amount_basis'] = '공고의 모집 계획, 실제 GP별 배정액 아님'
            parsed['blind_track_observed'] = True
            parsed['domestic_investment_verified'] = False
            readings.append(parsed)
    if len(readings) > 1:
        raise ValueError('같은 공고의 지원 양식 첨부가 여러 개임')
    if readings:
        return readings[0]
    text = ' '.join(n.get('attachment_texts', {}).values())
    compact = _compact(text)
    if not text:
        raise ValueError('모집 첨부 판독문 없음')
    if '프로젝트펀드' in compact[:400] and '블라인드' not in compact[:1000]:
        raise ValueError('프로젝트 전용 모집')
    if re.search(r'경영참여형사모|기관전용사모|\bPEF\b', text):
        raise ValueError('PE 가능 법형태와 독립 PE 블라인드 트랙 구분 필요')
    raise ValueError('지원하지 않는 모집 양식 또는 PE 트랙 미확인')


def _rosters(n, offering, *, valid_name, known):
    lines = [re.sub(r'\s+', ' ', s).strip() for s in n['body'].splitlines() if s.strip()]
    sections, current = {}, None
    for line in lines:
        heading = re.fullmatch(r'<\s*([^<>]+)\s*>', line)
        if heading:
            current = _compact(heading[1])
            if current in sections:
                raise ValueError('결과 명단 구분 중복')
            sections[current] = []
        elif line.startswith('*'):
            if _compact(line) != '*각리그별가나다순':
                raise ValueError('결과 명단의 추가 주석 판독 필요')
            current = None
        elif re.match(r'문의\s*[:：]', line):
            current = None
        elif current is not None and line != '운용사명':
            sections[current].append(line)
    required = {'PEF', 'PDF', '루키'} if offering['layout'] == 'blind_pef_pdf_rookie' else {'PEF', 'PDF'}
    if set(sections) != required:
        raise ValueError('PEF/PDF 결과 명단 구분 미확인')
    known = {_compact(k) for k in known}
    results, holds = [], []
    for track in offering['tracks']:
        label = track['label']
        section = '루키' if label == 'PEF(루키)' else label
        teams = []
        try:
            if len(sections[section]) != track['planned_fund_count']:
                raise ValueError('계획 펀드 수와 결과 명단 행 수 불일치')
            for line in sections[section]:
                # '/' is an observed Co-GP separator; spaces inside a legal name
                # never create additional teams or managers.
                names = [s.strip() for s in line.split('/')]
                if not 1 <= len(names) <= 2 or any(not name or not
                        (valid_name(_compact(name)) or _compact(name) in known) for name in names):
                    raise ValueError('결과 명단의 운용사 이름 규칙 미통과')
                teams.append({'managers': names, 'co_gp': len(names) > 1})
            names = [_compact(name) for team in teams for name in team['managers']]
            if len(names) != len(set(names)):
                raise ValueError('결과 명단의 운용사 중복')
            results.append({'label': label, 'fund_count': len(teams), 'manager_count': len(names),
                            'teams': teams, 'evidence': _evidence(n, '\n'.join(sections[section]))})
        except ValueError as exc:
            holds.append({'track': label, 'source_url': n['url'], 'reason': str(exc)})
    return results, holds


def review_bundle(bundle, *, valid_name, known_gp_names=()):
    """Return reproducible review groups, never public-program or approved GP rows.

    Callers must provide the shared GP-name rule and optionally already verified
    manager names. All candidates still require raw replay and domestic PE scope
    verification. No guessed budget, scope, GP name or loose date-based join.
    """
    notices, errors = _check_metadata(bundle)
    groups, unassigned = defaultdict(list), []
    for n in notices:
        if re.search(r'온라인\s*설명회|질의응답|FAQ|제출서류|서식|접수방식|소개자료', n['title'], re.I):
            unassigned.append({'url': n['url'], 'reason': '설명회·양식·보충 안내, 모집·결과로 쓰지 않음'})
            continue
        try:
            identity = _identity(n)
            groups[tuple(identity.values())].append((identity, n))
        except ValueError as exc:
            unassigned.append({'url': n['url'], 'reason': str(exc)})
    output = []
    for key, members in sorted(groups.items()):
        identity = members[0][0]
        entries = [n for _, n in members]
        offerings = [n for n in entries if notice_stage(n['title']) == '모집 공고']
        results = [n for n in entries if notice_stage(n['title']) in {'선정 결과', '최종 선정'}]
        group = {'identity': identity, 'notices': [{'url': n['url'], 'date': n['date'],
                  'title': n['title'], 'stage': notice_stage(n['title'])} for n in sorted(entries, key=lambda n: n['date'])],
                 'offering': None, 'rosters': [], 'holds': []}
        if len(offerings) != 1:
            group['holds'].append({'reason': '같은 펀드·연도·회차의 모집 공고가 없거나 여러 개임'})
        else:
            try:
                group['offering'] = _offering(offerings[0])
            except ValueError as exc:
                group['holds'].append({'source_url': offerings[0]['url'], 'reason': str(exc)})
        if group['offering'] and results:
            if len(results) != 1 or results[0]['date'] < offerings[0]['date']:
                group['holds'].append({'reason': '결과 공고가 여러 개이거나 모집보다 앞섬'})
            else:
                try:
                    rosters, held = _rosters(results[0], group['offering'], valid_name=valid_name, known=known_gp_names)
                    group['rosters'], group['holds'] = rosters, group['holds'] + held
                except ValueError as exc:
                    group['holds'].append({'source_url': results[0]['url'], 'reason': str(exc)})
        if group['offering']:
            group['holds'].append({'reason': '상세 HTML·첨부 원본 재생과 국내 투자범위 검증 필요'})
        output.append(group)
    return {'kind': KIND, 'publication_ready': False, 'raw_replay_required': True,
            'source_checked_at': bundle.get('checked_at'),
            'metadata_check': {'checked_notices': len(notices), 'errors': errors,
                               'detail_raw_present': bool(notices) and all(
                                   n.get('discovery_provenance', {}).get('detail_response_base64') for n in notices),
                               'attachment_bytes_present': any(n.get('attachment_bytes') for n in notices),
                               'detail_raw_replayed': False, 'attachment_bytes_replayed': False},
            'groups': output, 'unassigned': unassigned,
            'summary': {'retained_notices': len(bundle.get('notices', [])), 'groups': len(output),
                        'parsed_offerings': sum(g['offering'] is not None for g in output),
                        'parsed_pe_roster_tracks': sum(len(g['rosters']) for g in output),
                        'by_year': dict(sorted(Counter(n['date'][:4] for n in notices).items()))}}


def main(argv=None):
    """Review saved input only; never fetch sources, connect to a DB or publish."""
    import argparse
    from pathlib import Path
    try:
        from .lp_notice_publication import _rule_valid_name
    except ImportError:
        from lp_notice_publication import _rule_valid_name
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.bundle.resolve() == args.out.resolve():
        parser.error('검토 결과로 원문 묶음을 덮어쓸 수 없습니다')
    if args.bundle.stat().st_size > 40 * 1024 * 1024:
        parser.error('검토 묶음이 40MiB 제한을 초과했습니다')
    raw = args.bundle.read_bytes()
    report = review_bundle(json.loads(raw), valid_name=_rule_valid_name)
    report['bundle_sha256'] = hashlib.sha256(raw).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'summary': report['summary'], 'metadata_errors': len(report['metadata_check']['errors']),
                      'publication_ready': False, 'bundle_sha256': report['bundle_sha256']}, ensure_ascii=False))
    return 1 if report['metadata_check']['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
