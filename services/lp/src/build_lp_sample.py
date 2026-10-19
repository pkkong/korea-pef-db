"""Build the explicitly approved LP sample for Vercel delivery."""
import json
from pathlib import Path
from lp_program_service import build

ROOT = Path(__file__).resolve().parents[3]

def main():
    data = json.loads((ROOT / 'data/lp_programs_pilot.json').read_text())
    approved = {'ktcu-2026-blind-pef', 'moel-iaci-2026-pe', 'pck-pension-2026-h2-pe', 'kgrowth-2026-bank-valueup-3', 'koreapost-2026-domestic-pe'}
    data['programs'] = [p for p in data['programs'] if p['id'] in approved]
    if {p['id'] for p in data['programs']} != approved:
        raise ValueError('All five approved samples must exist')
    print(build(data, ROOT / 'services/lp/web/lp_samples'))

if __name__ == '__main__':
    main()
