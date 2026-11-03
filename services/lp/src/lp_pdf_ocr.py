"""Bounded local macOS Vision OCR. No source fetching, external services, or installs."""
import argparse
from collections import OrderedDict
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import tempfile

MAX_INPUT_BYTES = 12 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_PAGES = 12
MAX_PIXELS = 40_000_000
OCR_TIMEOUT = 180
COMPILE_TIMEOUT = 120
ENGINE = 'macos-vision-r3-pdfkit-v1'
CACHE_LIMIT = 16 * 1024 * 1024
_CACHE = OrderedDict()
_CACHE_BYTES = 0
HELPER = Path(__file__).resolve().parents[1] / 'tools' / 'ocr_pdf.swift'


def _apple_developer_path(path):
    # Hosted macOS runners select versioned Xcode application bundles.
    return bool(re.match(r'^/(?:Library/Developer/CommandLineTools/|Applications/Xcode(?:_[0-9]+(?:\.[0-9]+)*)?\.app/Contents/Developer/)', str(path)))


def _run(args, output, timeout):
    with output.open('wb') as target:
        try:
            # Never include renderer diagnostics or source text in raised errors.
            result = subprocess.run(args, stdout=target, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('local OCR process unavailable or timed out') from None
    if result.returncode != 0:
        raise ValueError('local OCR process failed (compiler, PDF, or required language unsupported)')
    if output.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError('local OCR output exceeded limit')
    return output.read_bytes()


def _compiler():
    if platform.system() != 'Darwin':
        raise ValueError('local OCR requires macOS Vision')
    try:
        result = subprocess.run(['/usr/bin/xcrun','--find','swiftc'], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('Apple Swift compiler unavailable') from None
    if len(result.stdout)>4096:raise ValueError('invalid compiler locator')
    locator = Path(result.stdout.decode('utf-8').strip())
    path = locator.resolve()
    if not _apple_developer_path(path) or path.name not in {'swiftc','swift-frontend','swift-driver'} or not path.is_file():
        raise ValueError('unapproved Apple compiler path')
    try:
        result = subprocess.run(['/usr/bin/xcrun','--show-sdk-path'],stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,timeout=10,check=True)
    except (OSError,subprocess.SubprocessError):raise ValueError('Apple macOS SDK unavailable') from None
    if len(result.stdout)>4096:raise ValueError('invalid SDK locator')
    sdk=Path(result.stdout.decode('utf-8').strip()).resolve()
    if not _apple_developer_path(sdk) or not sdk.is_dir() or not sdk.name.endswith('.sdk'):
        raise ValueError('unapproved macOS SDK path')
    return str(locator),str(sdk)


def _binary(helper_sha):
    compiler, sdk = _compiler()
    cache = Path(tempfile.gettempdir()) / ('lp-pdf-ocr-' + str(os.getuid()))
    cache.mkdir(mode=0o700, exist_ok=True)
    info=cache.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
        raise ValueError('unsafe OCR cache directory')
    # OS and compiler identity prevent reuse across toolchain/OS replacement.
    compiler_stat=os.stat(compiler)
    identity=helper_sha+platform.mac_ver()[0]+compiler+sdk+str(compiler_stat.st_mtime_ns)
    key=hashlib.sha256(identity.encode()).hexdigest()
    binary=cache/key
    if binary.exists():
        info=binary.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
            raise ValueError('unsafe OCR cached binary')
        return binary
    with tempfile.TemporaryDirectory(prefix='compile-',dir=cache) as directory:
        temporary=Path(directory)/'ocr'
        _run([compiler,'-sdk',sdk,'-O',str(HELPER),'-o',str(temporary)],Path(directory)/'compile-output',COMPILE_TIMEOUT)
        temporary.chmod(0o700)
        os.replace(temporary,binary)
    return binary


def validate_result(value, raw, helper_sha):
    """Validate process output before any caller can treat it as source evidence."""
    if not isinstance(value,dict) or value.get('version')!=1 or value.get('engine')!=ENGINE or value.get('revision')!=3:
        raise ValueError('unexpected OCR engine contract')
    if value.get('languages')!=['ko-KR','en-US'] or not isinstance(value.get('os_version'),str) or not value['os_version']:
        raise ValueError('missing required OCR language or OS identity')
    if value.get('input_sha256')!=hashlib.sha256(raw).hexdigest() or value.get('input_bytes')!=len(raw):
        raise ValueError('OCR source checksum mismatch')
    pages=value.get('pages')
    if not isinstance(pages,list) or not 1<=len(pages)<=MAX_PAGES:raise ValueError('OCR page limit')
    pixels=0
    for index,page in enumerate(pages,1):
        if not isinstance(page,dict) or page.get('page')!=index:raise ValueError('OCR page sequence mismatch')
        w,h=page.get('width'),page.get('height')
        if any(type(x) is not int or not 1<=x<=1800 for x in (w,h)):raise ValueError('OCR dimensions invalid')
        pixels+=w*h
        lines=page.get('lines')
        if not isinstance(lines,list) or len(lines)>10000:raise ValueError('OCR lines invalid')
        for line in lines:
            if not isinstance(line,dict) or not isinstance(line.get('text'),str) or '\x00' in line['text']:raise ValueError('OCR text invalid')
            confidence=line.get('confidence');bbox=line.get('bbox')
            if type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1:raise ValueError('OCR confidence invalid')
            if not isinstance(bbox,list) or len(bbox)!=4 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in bbox):raise ValueError('OCR bounds invalid')
        if page.get('text')!='\n'.join(line['text'] for line in lines):raise ValueError('OCR line/text mismatch')
    if pixels>MAX_PIXELS:raise ValueError('OCR pixel budget exceeded')
    return dict(value, helper_sha256=helper_sha)


def recognize_pdf(raw):
    global _CACHE_BYTES
    if not isinstance(raw,bytes) or not raw.startswith(b'%PDF-') or not 0<len(raw)<=MAX_INPUT_BYTES:
        raise ValueError('unsupported PDF or input byte limit')
    helper_sha=hashlib.sha256(HELPER.read_bytes()).hexdigest()
    key=(hashlib.sha256(raw).hexdigest(),helper_sha)
    if key in _CACHE:
        value,size=_CACHE[key];_CACHE.move_to_end(key)
        return validate_result(copy.deepcopy(value),raw,helper_sha)
    binary=_binary(helper_sha)
    with tempfile.TemporaryDirectory(prefix='lp-pdf-ocr-input-') as directory:
        path=Path(directory)/'input.pdf';path.write_bytes(raw)
        encoded=_run([str(binary),str(path)],Path(directory)/'output.json',OCR_TIMEOUT)
        try:value=json.loads(encoded,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite OCR JSON')))
        except (ValueError,UnicodeError):raise ValueError('invalid OCR JSON') from None
    result=validate_result(value,raw,helper_sha)
    size=len(encoded)
    if size<=CACHE_LIMIT:
        while _CACHE and (_CACHE_BYTES+size>CACHE_LIMIT or len(_CACHE)>=8):
            _,(_,removed)=_CACHE.popitem(last=False);_CACHE_BYTES-=removed
        _CACHE[key]=(copy.deepcopy(result),size);_CACHE_BYTES+=size
    return result



extract_pdf = recognize_pdf

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.input.stat().st_size>MAX_INPUT_BYTES:raise ValueError('PDF input byte limit')
    result=extract_pdf(args.input.read_bytes())
    args.output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False),encoding='utf-8')

if __name__=='__main__':main()
