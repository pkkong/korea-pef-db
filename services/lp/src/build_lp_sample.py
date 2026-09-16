"""Build the explicitly approved LP sample for Vercel delivery."""
import json
from pathlib import Path
from lp_program_service import build

ROOT = Path(__file__).resolve().parents[3]

def main():
    data = json.loads((ROOT / 'data/lp_programs_pilot.json').read_text())
    data['programs'] = [p for p in data['programs'] if p['id'] == 'ktcu-2026-blind-pef']
    if len(data['programs']) != 1:
        raise ValueError('The approved KTCU sample must exist exactly once')
    print(build(data, ROOT / 'services/newsletter/web/lp_samples'))

if __name__ == '__main__':
    main()
