from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blindcert.benchmark.system_models import generate_model


ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, value: object) -> str:
    text = json.dumps(value, separators=(',', ':')) + '\n'
    path.write_text(text)
    path.chmod(0o600)
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate fixed private efficiency inputs before registration.')
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/system_efficiency.yaml')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/system_workload')
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    if config['population_size'] % 4:
        parser.error('population_size must be divisible by four')
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    manifests = []
    for spec in config['models']:
        model = generate_model(spec, config['workload_seed'])
        directory = args.output / spec['name'].replace(' ', '_').replace(',', '_')
        directory.mkdir(mode=0o700)
        hashes = {'owner': write(directory / 'owner.json', {
            'model': spec, 'parameters': model.parameters, 'threshold': 0})}
        rng = random.Random(config['workload_seed'])
        records = [[], []]
        for index in range(config['population_size']):
            holder = index % 2
            stratum = (index // 2) % 2
            x = [rng.choice((-1, 0, 1)) for _ in range(model.layers[0])]
            y = model.predict(x)
            records[holder].append({'stratum': stratum, 'local_index': index // 4,
                                    'x': x, 'y': y, 'attribute': int(not y and index % 3 == 0),
                                    'nonce': str(rng.getrandbits(128))})
        for holder in range(2):
            hashes[f'holder{holder}'] = write(directory / f'holder{holder}.json', records[holder])
        manifests.append({**spec, 'parameter_count': len(model.parameters),
                          'population_size': config['population_size'], 'sample_size': config['sample_size'],
                          'workload_seed': config['workload_seed'], 'file_sha256': hashes,
                          'arithmetic': {'scale_bits': 0, 'rounding': 'exact integer',
                                         'signed': True, 'coefficient_bound': 1, 'input_bound': 1,
                                         'layers': model.bounds()},
                          'status': 'PREPARED_ONLY', 'circuit_semantics_validated': False})
    (args.output / 'manifest.json').write_text(json.dumps(manifests, indent=2) + '\n')
    print(json.dumps({'status': 'PREPARED_ONLY', 'models': len(manifests), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
