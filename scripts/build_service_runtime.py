"""Package exactly one web service and immutable shared presentation assets."""
from __future__ import annotations
import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'newsletter': ('app.py', 'index.py', 'newsletter_data.py', 'newsletter_ui.py', 'requirements.txt', 'vercel.json'),
    'lp': ('app.py', 'lp_program_data.py', 'requirements.txt', 'vercel.json'),
    'gp': ('app.py', 'index.py', 'gp_public_data.py', 'navigation.py', 'requirements.txt', 'vercel.json'),
}
DATA_PACK = 'gp_ranking_datapack_2025YE.xlsx'


def validate_data_pack(path: Path) -> None:
    if not path.is_file() or path.stat().st_size > 25 * 1024 * 1024 or not zipfile.is_zipfile(path):
        raise ValueError('GP ranking workbook is missing or invalid')
    with zipfile.ZipFile(path) as archive:
        if '[Content_Types].xml' not in archive.namelist() or 'xl/workbook.xml' not in archive.namelist():
            raise ValueError('GP workbook is not an XLSX document')
        if sum(entry.file_size for entry in archive.infolist()) > 100 * 1024 * 1024 or archive.testzip():
            raise ValueError('GP workbook integrity check failed')


def build(service: str, output: Path, gp_data_pack: Path | None = None) -> Path:
    if service not in FILES:
        raise ValueError('Unknown service')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Runtime output must be a new or empty directory')
    web = output / 'services' / service / 'web'
    web.mkdir(parents=True)
    for name in FILES[service]:
        shutil.copyfile(ROOT / 'services' / service / 'web' / name, web / name)
    shutil.copyfile(ROOT / 'services/shared/web/service_assets.py', web / 'service_assets.py')
    if service == 'gp':
        source = gp_data_pack or ROOT / 'services/gp/web/downloads' / DATA_PACK
        validate_data_pack(source)
        (web / 'downloads').mkdir()
        shutil.copyfile(source, web / 'downloads' / DATA_PACK)
    return web


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=FILES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gp-data-pack', type=Path)
    args = parser.parse_args()
    web = build(args.service, args.output, args.gp_data_pack)
    print(json.dumps({'service': args.service, 'web_root': str(web), 'files': sorted(p.name for p in web.iterdir())}))


if __name__ == '__main__':
    main()
