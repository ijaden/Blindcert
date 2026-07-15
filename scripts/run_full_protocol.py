from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "external"
NODE_BIN = EXTERNAL / "node-v24.18.0-linux-x64" / "bin"
SNARKJS = EXTERNAL / "node_modules" / ".bin" / "snarkjs"
CIRCOM = EXTERNAL / "circom"
CO_CIRCOM = EXTERNAL / "co-circom"
CO_EXAMPLES = EXTERNAL / "co-snarks-src" / "co-circom" / "co-circom" / "examples"
MPSPDZ = EXTERNAL / "mp-spdz-0.4.3"
WORK = ROOT / "results" / "full_protocol_lr4"


def env() -> dict[str, str]:
    out = dict(os.environ)
    out["PATH"] = f"{NODE_BIN}:{out.get('PATH', '')}"
    return out


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        env=env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    arg = Path(cmd[1]).name if len(cmd) > 1 else "cmd"
    log_name = f"{int(time.time() * 1000)}_{Path(cmd[0]).name}_{arg}.log"
    (WORK / "logs" / log_name).write_text(proc.stdout, encoding="utf-8")
    if proc.stdout:
        print(proc.stdout[-4000:])
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed with exit {proc.returncode}: {' '.join(cmd)}")
    return proc


def start(cmd: list[str]) -> subprocess.Popen[str]:
    print("$", " ".join(cmd), "&")
    return subprocess.Popen(
        cmd,
        cwd=WORK,
        env=env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def wait_all(processes: list[tuple[str, subprocess.Popen[str]]]) -> None:
    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    failed = []
    for name, proc in processes:
        stdout, _ = proc.communicate()
        (WORK / "logs" / f"{name}.log").write_text(stdout or "", encoding="utf-8")
        if stdout:
            print(stdout[-2000:])
        if proc.returncode != 0:
            failed.append((name, proc.returncode))
    if failed:
        raise RuntimeError(f"parallel commands failed: {failed}")


def require_tools() -> None:
    for path in [SNARKJS, CIRCOM, CO_CIRCOM, MPSPDZ / "mascot-party.x"]:
        if not path.exists():
            raise RuntimeError(f"missing required tool: {path}")


def prepare_dirs() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "lib").mkdir(exist_ok=True)
    (WORK / "configs").mkdir(exist_ok=True)
    (WORK / "data").mkdir(exist_ok=True)
    for source in (CO_EXAMPLES / "lib").glob("*.circom"):
        shutil.copy2(source, WORK / "lib" / source.name)
    shutil.copy2(ROOT / "circuits" / "blindcert_lr4.circom", WORK / "blindcert_lr4.circom")
    for name in ["cert0.der", "cert1.der", "cert2.der", "key0.der", "key1.der", "key2.der"]:
        shutil.copy2(CO_EXAMPLES / "data" / name, WORK / "data" / name)


def write_party_configs() -> list[Path]:
    configs = []
    for i in range(3):
        port = 12000 + i
        config = WORK / "configs" / f"party{i}.toml"
        config.write_text(
            f"""[compiler]
allow_leaky_loops = false
link_library = ["{WORK / 'lib'}"]

[vm]
allow_leaky_logs = false

[network]
my_id = {i}
bind_addr = "0.0.0.0:{port}"
key_path = "{WORK / 'data' / f'key{i}.der'}"

[[network.parties]]
id = 0
dns_name = "127.0.0.1:12000"
cert_path = "{WORK / 'data' / 'cert0.der'}"

[[network.parties]]
id = 1
dns_name = "127.0.0.1:12001"
cert_path = "{WORK / 'data' / 'cert1.der'}"

[[network.parties]]
id = 2
dns_name = "127.0.0.1:12002"
cert_path = "{WORK / 'data' / 'cert2.der'}"
""",
            encoding="utf-8",
        )
        configs.append(config)
    return configs


def write_input() -> dict[str, object]:
    numeric: dict[str, object] = {
        "archId": 1,
        "qScale": 0,
        "threshold": 3,
        "tauAllNum": 4,
        "tauAllDen": 4,
        "tau0Num": 2,
        "tau0Den": 2,
        "tau1Num": 2,
        "tau1Den": 2,
        "betaNum": 0,
        "cid": 101,
        "seed": 424242,
        "theta": [1, 1],
        "bias": 0,
        "rTheta": 777,
        "holder": [1, 1, 2, 2],
        "stratum": [0, 0, 1, 1],
        "localIndex": [0, 1, 0, 1],
        "nonce": [1101, 1102, 2201, 2202],
        "x": [[2, 2], [0, 1], [3, 0], [1, 1]],
        "y": [1, 0, 1, 0],
        "attribute": [0, 0, 0, 1],
    }
    def stringify(value: object) -> object:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, list):
            return [stringify(v) for v in value]
        return value

    data = {k: stringify(v) for k, v in numeric.items()}
    (WORK / "input.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return numeric


def compile_and_setup() -> None:
    run([str(CIRCOM), "blindcert_lr4.circom", "--r1cs", "--wasm", "--sym", "-o", str(WORK)], cwd=WORK)
    run([str(SNARKJS), "r1cs", "info", str(WORK / "blindcert_lr4.r1cs")], cwd=WORK)
    ptau0 = WORK / "pot14_0000.ptau"
    ptau1 = WORK / "pot14_0001.ptau"
    ptau_final = WORK / "pot14_final.ptau"
    if not ptau_final.exists():
        run([str(SNARKJS), "powersoftau", "new", "bn128", "14", str(ptau0), "-v"], cwd=WORK)
        run(
            [
                str(SNARKJS),
                "powersoftau",
                "contribute",
                str(ptau0),
                str(ptau1),
                "--name=blindcert-demo",
                "-v",
                "-e=blindcert deterministic demo entropy",
            ],
            cwd=WORK,
        )
        run([str(SNARKJS), "powersoftau", "prepare", "phase2", str(ptau1), str(ptau_final), "-v"], cwd=WORK)
    zkey0 = WORK / "blindcert_lr4_0000.zkey"
    zkey = WORK / "blindcert_lr4.zkey"
    if not zkey.exists():
        run([str(SNARKJS), "groth16", "setup", str(WORK / "blindcert_lr4.r1cs"), str(ptau_final), str(zkey0)], cwd=WORK)
        run(
            [
                str(SNARKJS),
                "zkey",
                "contribute",
                str(zkey0),
                str(zkey),
                "--name=blindcert-zkey",
                "-v",
                "-e=blindcert zkey deterministic entropy",
            ],
            cwd=WORK,
        )
    run([str(SNARKJS), "zkey", "export", "verificationkey", str(zkey), str(WORK / "verification_key.json")], cwd=WORK)


def run_single_prover_baseline() -> None:
    wasm = WORK / "blindcert_lr4_js" / "blindcert_lr4.wasm"
    witness = WORK / "witness.wtns"
    run([str(NODE_BIN / "node"), str(WORK / "blindcert_lr4_js" / "generate_witness.js"), str(wasm), str(WORK / "input.json"), str(witness)], cwd=WORK)
    run(
        [
            str(SNARKJS),
            "groth16",
            "prove",
            str(WORK / "blindcert_lr4.zkey"),
            str(witness),
            str(WORK / "single_proof.json"),
            str(WORK / "single_public.json"),
        ],
        cwd=WORK,
    )
    run(
        [
            str(SNARKJS),
            "groth16",
            "verify",
            str(WORK / "verification_key.json"),
            str(WORK / "single_public.json"),
            str(WORK / "single_proof.json"),
        ],
        cwd=WORK,
    )


def run_mpspdz_baseline() -> dict[str, object]:
    proc = run(
        ["python3", "-m", "blindcert.cli", "evaluate", "--backend", "mpspdz"],
        cwd=ROOT,
        check=True,
    )
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def run_proof_from_current_witness_shares(configs: list[Path], log_prefix: str) -> None:
    proof_procs = []
    for i, cfg in enumerate(configs):
        cmd = [
            str(CO_CIRCOM),
            "generate-proof",
            "groth16",
            "--witness",
            str(WORK / f"witness.wtns.{i}.shared"),
            "--zkey",
            str(WORK / "blindcert_lr4.zkey"),
            "--protocol",
            "REP3",
            "--curve",
            "BN254",
            "--config",
            str(cfg),
        ]
        if i == 0:
            cmd.extend(["--out", str(WORK / "collaborative_proof.json"), "--public-input", str(WORK / "collaborative_public.json")])
        proof_procs.append((f"{log_prefix}_co_generate_proof_party{i}", start(cmd)))
    wait_all(proof_procs)


def run_collaborative(configs: list[Path]) -> str:
    run(
        [
            str(CO_CIRCOM),
            "split-input",
            "--circuit",
            str(WORK / "blindcert_lr4.circom"),
            "--input",
            str(WORK / "input.json"),
            "--protocol",
            "REP3",
            "--curve",
            "BN254",
            "--out-dir",
            str(WORK),
            "--config",
            str(configs[0]),
        ],
        cwd=WORK,
    )
    witness_procs = []
    for i, cfg in enumerate(configs):
        witness_procs.append(
            (
                f"co_generate_witness_party{i}",
                start(
                    [
                        str(CO_CIRCOM),
                        "generate-witness",
                        "-O2",
                        "--input",
                        str(WORK / f"input.json.{i}.shared"),
                        "--circuit",
                        str(WORK / "blindcert_lr4.circom"),
                        "--protocol",
                        "REP3",
                        "--curve",
                        "BN254",
                        "--config",
                        str(cfg),
                        "--out",
                        str(WORK / f"witness.wtns.{i}.shared"),
                    ]
                ),
            )
        )
    wait_all(witness_procs)
    witness_source = "co-circom generate-witness"
    try:
        run_proof_from_current_witness_shares(configs, "mpc_witness")
    except RuntimeError as exc:
        (WORK / "logs" / "co_circom_generate_witness_proof_failed.txt").write_text(
            str(exc) + "\nFalling back to split-witness shares from the verified witness.wtns.\n",
            encoding="utf-8",
        )
        witness_source = "split-witness fallback after co-circom generate-witness proof incompatibility"
        run(
            [
                str(CO_CIRCOM),
                "split-witness",
                "--witness",
                str(WORK / "witness.wtns"),
                "--r1cs",
                str(WORK / "blindcert_lr4.r1cs"),
                "--protocol",
                "REP3",
                "--curve",
                "BN254",
                "--out-dir",
                str(WORK),
            ],
            cwd=WORK,
        )
        run_proof_from_current_witness_shares(configs, "split_witness")
    run(
        [
            str(CO_CIRCOM),
            "verify",
            "groth16",
            "--proof",
            str(WORK / "collaborative_proof.json"),
            "--vk",
            str(WORK / "verification_key.json"),
            "--public-input",
            str(WORK / "collaborative_public.json"),
            "--curve",
            "BN254",
        ],
        cwd=WORK,
    )
    return witness_source


def write_passport(input_data: dict[str, object], mpc_result: dict[str, object], witness_source: str) -> None:
    public = json.loads((WORK / "collaborative_public.json").read_text(encoding="utf-8"))
    proof = json.loads((WORK / "collaborative_proof.json").read_text(encoding="utf-8"))
    names = ["modelCommitment", "benchmarkDigest", "policyDigest", "sampleDigest", "sid", "pass"]
    statement = dict(zip(names, public, strict=True))
    passport = {
        "backend_id": "co-circom-groth16-rep3",
        "expiry": int(time.time()) + 3600,
        "public_statement": statement,
        "proof": proof,
        "public_input": public,
        "verification_key": json.loads((WORK / "verification_key.json").read_text(encoding="utf-8")),
        "transcript": {
            "paper": str(Path("../output (3).pdf")),
            "circuit": "blindcert_lr4.circom",
            "model_arch": "logistic_regression",
            "sample_rule": "sample without replacement demo: all four registered records",
            "mpc_result": mpc_result,
            "collaborative_witness_source": witness_source,
            "input_manifest": {
                "holders": input_data["holder"],
                "strata": input_data["stratum"],
                "indices": input_data["localIndex"],
                "threshold": input_data["threshold"],
                "policy": {
                    "tau_all": [input_data["tauAllNum"], input_data["tauAllDen"]],
                    "tau_g0": [input_data["tau0Num"], input_data["tau0Den"]],
                    "tau_g1": [input_data["tau1Num"], input_data["tau1Den"]],
                    "beta": input_data["betaNum"],
                },
            },
        },
    }
    (WORK / "passport.json").write_text(json.dumps(passport, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "passport": str(WORK / "passport.json"), "public_statement": statement}, indent=2))


def main() -> int:
    require_tools()
    prepare_dirs()
    configs = write_party_configs()
    input_data = write_input()
    compile_and_setup()
    run_single_prover_baseline()
    mpc_result = run_mpspdz_baseline()
    witness_source = run_collaborative(configs)
    write_passport(input_data, mpc_result, witness_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
