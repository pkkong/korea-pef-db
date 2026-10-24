"""Bounded DNS metadata fallback; origin HTTPS remains in its existing session."""
import ipaddress
import json
import math
from pathlib import Path
import socket
import subprocess
import tempfile

HOST = 'www.kdb.co.kr'
DNS_URL = 'https://dns.google/resolve?name=www.kdb.co.kr&type=A&cd=0&edns_client_subnet=0.0.0.0%2F0'
MAX_BYTES = 16 * 1024


def _fail():
    return ValueError('KDB alternate DNS response invalid or unavailable')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _name(value):
    if not isinstance(value, str) or len(value) > 254:
        raise _fail()
    value = value.lower().removesuffix('.')
    labels = value.split('.')
    if any(not label or len(label) > 63 or not label.isascii()
           or not all(c.isalnum() or c == '-' for c in label)
           or label.startswith('-') or label.endswith('-') for label in labels):
        raise _fail()
    return value


def _addresses(raw):
    try:
        data = json.loads(raw, object_pairs_hook=_unique)
        if (not isinstance(data, dict) or type(data.get('Status')) is not int
                or data['Status'] != 0 or data.get('TC') is not False
                or data.get('CD') is not False):
            raise _fail()
        question = data.get('Question')
        if (not isinstance(question, list) or len(question) != 1
                or not isinstance(question[0], dict)
                or question[0].get('name') != HOST + '.'
                or type(question[0].get('type')) is not int or question[0]['type'] != 1):
            raise _fail()
        answers = data.get('Answer')
        if not isinstance(answers, list) or not 1 <= len(answers) <= 32:
            raise _fail()
        aliases, addresses = {}, {}
        for record in answers:
            if (not isinstance(record, dict) or type(record.get('type')) is not int
                    or record['type'] not in {1, 5} or type(record.get('TTL')) is not int
                    or record['TTL'] < 0):
                raise _fail()
            name = _name(record.get('name'))
            if record['type'] == 5:
                target = _name(record.get('data'))
                if name in aliases and aliases[name] != target:
                    raise _fail()
                aliases[name] = target
            else:
                if not isinstance(record.get('data'), str):
                    raise _fail()
                address = ipaddress.IPv4Address(record['data'])
                if (not address.is_global or address.is_multicast or address.is_loopback
                        or address.is_private or address.is_reserved or address.is_link_local
                        or address.is_unspecified):
                    raise _fail()
                addresses.setdefault(name, set()).add(str(address))
        if set(aliases) & set(addresses):
            raise _fail()
        seen, current = set(), HOST
        while current in aliases:
            if current in seen or len(seen) >= 8:
                raise _fail()
            seen.add(current)
            current = aliases[current]
        if current in seen or not addresses.get(current):
            raise _fail()
        seen.add(current)
        if (set(aliases) | set(addresses)) - seen:
            raise _fail()
        return sorted(addresses[current])[:2]
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise _fail() from None


def resolve_kdb_ipv4(host, port, timeout=5):
    """Resolve only KDB A records; no origin requests or persistent DNS cache."""
    if (host != HOST or type(port) is not int or port != 443
            or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 0 < timeout <= 5):
        raise ValueError('KDB alternate DNS request not permitted')
    try:
        with tempfile.TemporaryDirectory(prefix='lp-kdb-dns-') as folder:
            body = Path(folder) / 'response'
            command = ['curl', '--disable', '--proxy', '', '--fail', '--silent', '--show-error',
                       '--retry', '0', '--max-time', str(timeout), '--max-filesize', str(MAX_BYTES),
                       '--proto', '=https', '--proto-redir', '=https',
                       '--header', 'Accept: application/dns-json', '--header', 'Accept-Encoding: identity',
                       '--output', str(body), '--write-out', '%{http_code}', DNS_URL]
            result = subprocess.run(command, capture_output=True, timeout=timeout)
            if result.returncode != 0 or result.stdout != b'200':
                raise _fail()
            with body.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            if not raw or len(raw) > MAX_BYTES:
                raise _fail()
            addresses = _addresses(raw)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise _fail() from None
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port))
            for address in addresses]
