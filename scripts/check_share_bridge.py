from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blindcert.bridge.mpspdz_rep3 import SCALAR_FIELD


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'external'
MPC = TOOLS / 'mp-spdz-0.4.3'
CO = TOOLS / 'co-circom'
EXAMPLES = TOOLS / 'co-snarks-src/co-circom/co-circom/examples'
WORK = ROOT / 'results/share_bridge' / uuid.uuid4().hex
ENV = {**os.environ, 'PATH': str(TOOLS / 'node-v24.18.0-linux-x64/bin') + ':' + os.environ['PATH']}


def run(command: list[str], cwd: Path = WORK) -> None:
    result = subprocess.run(command, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=120)
    (WORK / f'command-{time.time_ns()}.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'{command[0]} exited {result.returncode}: {result.stderr[-1000:]}')


def group(commands: list[list[str]], directories: list[Path], label: str) -> None:
    processes = []
    try:
        for i, (command, directory) in enumerate(zip(commands, directories)):
            log = (WORK / f'{label}-party{i}.log').open('w')
            try:
                proc = subprocess.Popen(command, cwd=directory, env=ENV, stdout=log, stderr=subprocess.STDOUT)
            finally:
                log.close()
            processes.append(proc)
        deadline = time.monotonic() + 120
        codes = [p.wait(timeout=max(.01, deadline - time.monotonic())) for p in processes]
        if any(codes):
            raise RuntimeError(f'{label} failed: {codes}; logs: {WORK}')
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def main() -> None:
    WORK.mkdir(parents=True, mode=0o700)
    (WORK / 'layout.json').write_text(json.dumps({'a': 1, 'b': 1, 'c': 1}))
    name = 'blindcert_bridge_' + WORK.name
    source = MPC / 'Programs/Source' / (name + '.mpc')
    source.write_text("from Compiler.library import check_point\na = sint.get_input_from(0)\nb = sint.get_input_from(1)\nc = sint.get_input_from(2)\nproduct = a * b * c\nfor value in [a, b, c]:\n    masked = value + sint.get_random()\n    print_ln('MASKED=%s', masked.reveal())\ncheck_point()\nsint.write_to_file([a, b, c], position=0)\nprint_ln('PRODUCT=%s', product.reveal())\ncheck_point()\nprint_ln('BRIDGE_MAC_CHECK_COMPLETE')\n")
    run([sys.executable, 'compile.py', '-F', '64', name], MPC)
    directories = []
    for i, value in enumerate([7, -3, 2]):
        directory = WORK / f'party{i}'
        (directory / 'Player-Data').mkdir(parents=True)
        (directory / 'Programs').symlink_to(MPC / 'Programs', target_is_directory=True)
        (directory / f'Player-Data/Input-P{i}-0').write_text(str(value) + '\n')
        directories.append(directory)
    group([[str(MPC / 'mascot-party.x'), '-N', '3', '-P', str(SCALAR_FIELD), '-pn', '15360',
            '-h', '127.0.0.1', '-p', str(i), name] for i in range(3)], directories, 'mascot')
    if 'BRIDGE_MAC_CHECK_COMPLETE' not in (WORK / 'mascot-party0.log').read_text():
        raise RuntimeError('missing completed MAC check')
    if 'PRODUCT=-42' not in (WORK / 'mascot-party0.log').read_text():
        raise RuntimeError('MASCOT reference prediction mismatch')
    for i in range(3):
        prev = (i - 1) % 3
        run([sys.executable, '-m', 'blindcert.bridge.mpspdz_rep3',
             '--own', str(directories[i] / f'Persistence/Transactions-P{i}.data'),
             '--previous', str(directories[prev] / f'Persistence/Transactions-P{prev}.data'),
             '--layout', str(WORK / 'layout.json'), '--out', str(directories[i] / 'input.shared')], ROOT)
        for j in range(3):
            shutil.copy2(EXAMPLES / f'data/cert{j}.der', directories[i] / f'cert{j}.der')
        shutil.copy2(EXAMPLES / f'data/key{i}.der', directories[i] / 'key.der')
        config = f'[network]\nmy_id = {i}\nbind_addr = "127.0.0.1:{15400+i}"\nkey_path = "{directories[i] / "key.der"}"\n'
        for j in range(3):
            config += f'\n[[network.parties]]\nid = {j}\ndns_name = "127.0.0.1:{15400+j}"\ncert_path = "{directories[i] / f"cert{j}.der"}"\n'
        (directories[i] / 'network.toml').write_text(config)
    circuit = WORK / 'bridge.circom'
    circuit.write_text('pragma circom 2.0.0;\ntemplate Bridge() {\n signal input a;\n signal input b;\n signal input c;\n signal t;\n signal output out;\n t <== a*b;\n out <== t*c;\n}\ncomponent main = Bridge();\n')
    run([str(TOOLS / 'circom'), str(circuit), '--r1cs', '--wasm', '--sym', '--O0', '-o', str(WORK)])
    commands = [[str(CO), 'generate-witness', '-O0', '--input', str(d / 'input.shared'), '--circuit', str(circuit),
                 '--protocol', 'REP3', '--curve', 'BN254', '--config', str(d / 'network.toml'), '--out', str(d / 'witness.shared')] for d in directories]
    group(commands, directories, 'co-witness')
    snark = str(TOOLS / 'node_modules/.bin/snarkjs')
    run([snark, 'powersoftau', 'new', 'bn128', '4', 'pot.ptau'])
    run([snark, 'powersoftau', 'prepare', 'phase2', 'pot.ptau', 'final.ptau'])
    run([snark, 'groth16', 'setup', 'bridge.r1cs', 'final.ptau', 'bridge.zkey'])
    run([snark, 'zkey', 'export', 'verificationkey', 'bridge.zkey', 'vk.json'])
    commands = []
    for i, d in enumerate(directories):
        command = [str(CO), 'generate-proof', 'groth16', '--witness', str(d / 'witness.shared'),
                   '--zkey', str(WORK / 'bridge.zkey'), '--protocol', 'REP3', '--curve', 'BN254', '--config', str(d / 'network.toml')]
        if i == 0:
            command += ['--out', str(WORK / 'proof.json'), '--public-input', str(WORK / 'public.json')]
        commands.append(command)
    group(commands, directories, 'co-prove')
    expected = [str((-42) % SCALAR_FIELD)]
    if json.loads((WORK / 'public.json').read_text()) != expected:
        raise RuntimeError('co-circom public output differs from integer reference')
    run([str(CO), 'verify', 'groth16', '--proof', str(WORK / 'proof.json'), '--vk', str(WORK / 'vk.json'), '--public-input', str(WORK / 'public.json'), '--curve', 'BN254'])
    result = {'verified': True, 'mpc_parties': 3, 'proof_parties': 3,
              'mac_checked_before_conversion': True, 'plaintext_witness_used': False,
              'relation': 'three-private-input multiplication; bridge self-check only',
              'security': 'REP3 honest-majority semi-honest, at most one passive corruption; local trusted files',
              'srs': 'test-only insecure initialization; not an experiment or production setup', 'directory': str(WORK)}
    (WORK / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if WORK.exists():
            (WORK / 'result.json').write_text(json.dumps({'verified': False, 'error': str(exc), 'directory': str(WORK)}, indent=2) + '\n')
        raise
