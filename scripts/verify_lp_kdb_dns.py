"""Verify KDB DNS-only recovery with actual official HTTPS, without DB writes."""
import argparse
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.lp.src.collect_lp_institution_boards import collect, load_configs, validate_notice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    original = socket.getaddrinfo

    def failing_kdb(host, *positional, **keywords):
        if host == 'www.kdb.co.kr':
            raise socket.gaierror(8, 'injected official host resolver failure')
        return original(host, *positional, **keywords)

    # Only the two Python DNS lookups fail. DNS metadata and origin HTTPS are real.
    with patch.object(socket, 'getaddrinfo', side_effect=failing_kdb):
        report = collect({'kdb': load_configs()['kdb']})
    args.output.with_name('lp-kdb-injected-collection.json').write_text(
        json.dumps(report, ensure_ascii=False) + '\n')
    for notice in report['notices']:
        validate_notice(notice, report['checked_at'])
    holds = report.get('holds', [])
    unexpected = [hold for hold in holds if not (
        hold.get('stage') == 'institution_attachment'
        and hold.get('error') == 'offering ZIP exceeds bounded extraction limits')]
    decoded = sum(bool(text.strip()) for notice in report['notices']
                  for text in notice.get('attachment_texts', {}).values())
    coverage = report['coverage']['kdb']
    result = {'mode': 'two injected Python DNS failures; actual alternate DNS and official HTTPS; no DB writes',
              'coverage': coverage, 'holds': holds, 'unexpected_holds': unexpected,
              'validated_notices': len(report['notices']), 'decoded_attachments': decoded}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    assert not unexpected, 'KDB official collection failed'
    assert report['notices'] and decoded > 0, 'KDB original documents or decoded attachments missing'
    assert coverage['alternate_dns_lookup_count'] > 0, 'KDB alternate DNS path did not execute'
    assert coverage['dns_ipv4_fetch_count'] > 0, 'KDB original HTTPS path did not execute'


if __name__ == '__main__':
    main()
