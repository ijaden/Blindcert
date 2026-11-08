from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description='Verify completed single-prover controls after all measurements.')
    parser.add_argument('--input',type=Path,required=True)
    args = parser.parse_args()
    directory = args.input.resolve()
    data = json.loads((directory/'summary.json').read_text())
    if len(data['models']) != len(data['config']['models']):
        parser.error('wait for the complete model sequence before running controls')
    results = []
    for row in data['models']:
        if row['status'] != 'OK':
            continue
        name = row['model'].replace(' ','_').replace(',','_')
        control = directory/'single'/name
        artifact = directory/'artifacts'/name
        proc = subprocess.run([str(ROOT/'external/co-circom'),'verify','groth16','--proof',str(control/'proof.json'),
                               '--public-input',str(control/'public.json'),'--vk',str(artifact/'vk.json'),'--curve','BN254'],
                              text=True,capture_output=True,timeout=120)
        (control/'verification.log').write_text(proc.stdout+proc.stderr)
        row['single_control_verified'] = proc.returncode == 0
        results.append({'model':row['model'],'verified':proc.returncode==0,'returncode':proc.returncode})
        if proc.returncode:
            row['status'] = 'FAILED'
            row['reason'] = 'single-prover control verification failed; system certification remains recorded separately'
    (directory/'summary.json').write_text(json.dumps(data,indent=2)+'\n')
    (directory/'control_verification.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results))
    return 0 if all(row['verified'] for row in results) else 2


if __name__ == '__main__':
    raise SystemExit(main())
