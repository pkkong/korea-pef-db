"""Read-only collection of configured public Mirae Asset searches through curl."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import lp_board_adapter_miraeasset as board
from .collect_lp_institution_boards import MAX_BYTES, collect, load_configs


def collect_via_curl(out, *, process_factory=subprocess.Popen):
    config = load_configs()['moel_eif_ocio']
    out.mkdir(parents=True, exist_ok=False)
    receipts = []

    def fetch(url, referer=None):
        if urlsplit(url).path == board.LIST_PATH:
            board.listing_url_allowed(url, config)
        else:
            board.detail_query(url, config)
        command = ['curl', '--disable', '--silent', '--http1.1', '--proto', '=https', '--noproxy', '*',
                   '--max-time', '20', '--max-filesize', str(MAX_BYTES), '--write-out', '%{stderr}%{http_code}',
                   '--user-agent', 'Mozilla/5.0 (LP official board collector)', '--header', 'Accept-Encoding: identity',
                   '--header', 'Connection: close', '--referer', referer or config['listing_url'], url]
        stamp = datetime.now(timezone.utc).isoformat()
        with process_factory(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            prefix = process.stdout.read(MAX_BYTES + 1)
            oversized = len(prefix) > MAX_BYTES
            if oversized:
                process.kill()
            status = process.stderr.read(4)
            exit_code = process.wait(timeout=22)
        raw = prefix[:MAX_BYTES]
        filename = f'response-{len(receipts) + 1}.bin'
        (out / filename).write_bytes(raw)
        http_status = int(status) if len(status) == 3 and status.isdigit() else None
        receipts.append({'url': url, 'checked_at': stamp, 'response_file': filename,
                         'http_status': http_status, 'curl_exit': exit_code, 'truncated': oversized,
                         'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        (out / 'transport-receipts.json').write_text(json.dumps(receipts, ensure_ascii=False, indent=2))
        if exit_code != 0 or oversized or http_status != 200:
            raise ValueError('미래에셋증권 curl 원응답 수신 미완료')
        return raw

    report = collect({'moel_eif_ocio': config}, lambda _: fetch, retry_failures=False)
    (out / 'eif-ocio-collection.json').write_text(json.dumps(report, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    collect_via_curl(args.out)


if __name__ == '__main__':
    main()
