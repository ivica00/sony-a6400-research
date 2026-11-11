"""Generate the declared ZV-E10 -> a6400 UVC overlay plan (E0322).

Reads the E0321 enablement manifest and writes the hash-pinned overlay plan.
Offline only: no camera access, no deployment, no file writes to any target.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.execution.zve10_uvc_overlay import build_overlay_plan

MANIFEST = ROOT / 'artifacts/analysis/e0321-uvc-enablement-manifest.json'
OUTPUT = ROOT / 'artifacts/analysis/e0322-uvc-overlay-plan.json'


def main():
    if not MANIFEST.is_file():
        print('missing manifest; run tools/research/uvc_enablement_manifest.py first')
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    plan = build_overlay_plan(manifest)
    plan['manifest'] = str(MANIFEST.relative_to(ROOT))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(plan, indent=2), encoding='utf-8')
    print('readiness:', plan['readiness'])
    for reason in plan['blocking_reasons']:
        print(' -', reason)
    print('operations:')
    for operation in plan['operations']:
        print(' ', operation['action'], operation['component'], '->',
              operation['target'], '(' + str(operation['a6400_status']) + ')')
    print('plan:', OUTPUT.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
