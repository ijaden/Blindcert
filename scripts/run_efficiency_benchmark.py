from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "external"
NODE_BIN = EXTERNAL / "node-v24.18.0-linux-x64" / "bin"
SNARKJS = EXTERNAL / "node_modules" / ".bin" / "snarkjs"
CIRCOM = EXTERNAL / "circom"
CO_CIRCOM = EXTERNAL / "co-circom"
CO_EXAMPLES = EXTERNAL / "co-snarks-src" / "co-circom" / "co-circom" / "examples"
MPSPDZ = EXTERNAL / "mp-spdz-0.4.3"
WORK = ROOT / "results" / "efficiency_lr4"


def env() -> dict[str, str]:
    out = dict(os.environ)
    out["PATH"] = f"{NODE_BIN}:{out.get('PATH', '')}"
    return out


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> tuple[subprocess.CompletedProcess[str], float]:
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        env=env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.perf_counter() - start
    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    stem = "_".join(Path(part).name for part in cmd[:3])
    (WORK / "logs" / f"{int(time.time() * 1000)}_{stem}.log").write_text(proc.stdout or "", encoding="utf-8")
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed with exit {proc.returncode}: {' '.join(cmd)}\n{proc.stdout[-4000:]}")
    return proc, elapsed


def start(cmd: list[str]) -> tuple[subprocess.Popen[str], float]:
    proc = subprocess.Popen(
        cmd,
        cwd=WORK,
        env=env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc, time.perf_counter()


def wait_all(processes: list[tuple[str, subprocess.Popen[str], float]]) -> dict[str, float]:
    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    elapsed: dict[str, float] = {}
    failures: list[tuple[str, int]] = []
    for name, proc, started in processes:
        stdout, _ = proc.communicate()
        elapsed[name] = time.perf_counter() - started
        (WORK / "logs" / f"{name}.log").write_text(stdout or "", encoding="utf-8")
        if proc.returncode != 0:
            failures.append((name, proc.returncode))
    if failures:
        raise RuntimeError(f"parallel commands failed: {failures}")
    return elapsed


def require_tools() -> None:
    for path in [SNARKJS, CIRCOM, CO_CIRCOM, MPSPDZ / "mascot-party.x", NODE_BIN / "node"]:
        if not path.exists():
            raise RuntimeError(f"missing required tool: {path}")


def prepare_dirs(clean: bool) -> None:
    if clean and WORK.exists():
        shutil.rmtree(WORK)
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
        port = 12100 + i
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
dns_name = "127.0.0.1:12100"
cert_path = "{WORK / 'data' / 'cert0.der'}"

[[network.parties]]
id = 1
dns_name = "127.0.0.1:12101"
cert_path = "{WORK / 'data' / 'cert1.der'}"

[[network.parties]]
id = 2
dns_name = "127.0.0.1:12102"
cert_path = "{WORK / 'data' / 'cert2.der'}"
""",
            encoding="utf-8",
        )
        configs.append(config)
    return configs


def write_input() -> None:
    numeric: dict[str, Any] = {
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

    def stringify(value: Any) -> Any:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, list):
            return [stringify(v) for v in value]
        return value

    (WORK / "input.json").write_text(json.dumps({k: stringify(v) for k, v in numeric.items()}, indent=2), encoding="utf-8")


def parse_r1cs_info(text: str) -> dict[str, int]:
    metrics: dict[str, int] = {}
    mapping = {
        "# of Wires": "wires",
        "# of Constraints": "constraints",
        "# of Private Inputs": "private_inputs",
        "# of Public Inputs": "public_inputs",
        "# of Outputs": "public_outputs",
    }
    for label, key in mapping.items():
        match = re.search(rf"{re.escape(label)}:\s+([0-9]+)", text)
        if match:
            metrics[key] = int(match.group(1))
    return metrics


def compile_and_setup() -> tuple[dict[str, int], dict[str, float]]:
    times: dict[str, float] = {}
    _, times["circom_compile_s"] = run([str(CIRCOM), "blindcert_lr4.circom", "--r1cs", "--wasm", "--sym", "-o", str(WORK)], cwd=WORK)
    info_proc, times["r1cs_info_s"] = run([str(SNARKJS), "r1cs", "info", str(WORK / "blindcert_lr4.r1cs")], cwd=WORK)
    ptau0 = WORK / "pot14_0000.ptau"
    ptau1 = WORK / "pot14_0001.ptau"
    ptau_final = WORK / "pot14_final.ptau"
    _, times["powersoftau_new_s"] = run([str(SNARKJS), "powersoftau", "new", "bn128", "14", str(ptau0), "-v"], cwd=WORK)
    _, times["powersoftau_contribute_s"] = run(
        [
            str(SNARKJS),
            "powersoftau",
            "contribute",
            str(ptau0),
            str(ptau1),
            "--name=blindcert-efficiency",
            "-v",
            "-e=blindcert deterministic benchmark entropy",
        ],
        cwd=WORK,
    )
    _, times["powersoftau_prepare_s"] = run([str(SNARKJS), "powersoftau", "prepare", "phase2", str(ptau1), str(ptau_final), "-v"], cwd=WORK)
    zkey0 = WORK / "blindcert_lr4_0000.zkey"
    zkey = WORK / "blindcert_lr4.zkey"
    _, times["groth16_setup_s"] = run([str(SNARKJS), "groth16", "setup", str(WORK / "blindcert_lr4.r1cs"), str(ptau_final), str(zkey0)], cwd=WORK)
    _, times["zkey_contribute_s"] = run(
        [
            str(SNARKJS),
            "zkey",
            "contribute",
            str(zkey0),
            str(zkey),
            "--name=blindcert-zkey",
            "-v",
            "-e=blindcert zkey deterministic benchmark entropy",
        ],
        cwd=WORK,
    )
    _, times["vk_export_s"] = run([str(SNARKJS), "zkey", "export", "verificationkey", str(zkey), str(WORK / "verification_key.json")], cwd=WORK)
    return parse_r1cs_info(info_proc.stdout), times


def run_single_prover() -> dict[str, Any]:
    wasm = WORK / "blindcert_lr4_js" / "blindcert_lr4.wasm"
    witness = WORK / "witness.wtns"
    _, witness_s = run(
        [str(NODE_BIN / "node"), str(WORK / "blindcert_lr4_js" / "generate_witness.js"), str(wasm), str(WORK / "input.json"), str(witness)],
        cwd=WORK,
    )
    _, prove_s = run(
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
    _, verify_s = run(
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
    return {
        "single_witness_s": witness_s,
        "single_prove_s": prove_s,
        "single_verify_s": verify_s,
    }


def run_mpspdz() -> dict[str, Any]:
    proc, wall_s = run(["python3", "-m", "blindcert.cli", "evaluate", "--backend", "mpspdz"], cwd=ROOT)
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return {
        "mpspdz_wall_s": wall_s,
        "mpspdz_online_s": float(payload["online_seconds"]),
        "mpspdz_communication_bytes": int(payload["communication_bytes"]),
    }


def run_collaborative(configs: list[Path], attempt_mpc_witness_proof: bool) -> dict[str, Any]:
    _, split_input_s = run(
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

    witness_procs: list[tuple[str, subprocess.Popen[str], float]] = []
    for i, cfg in enumerate(configs):
        proc, started = start(
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
        )
        witness_procs.append((f"co_generate_witness_party{i}", proc, started))
    witness_times = wait_all(witness_procs)

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
        proc, started = start(cmd)
        proof_procs.append((f"generated_witness_proof_party{i}", proc, started))
    proof_times = wait_all(proof_procs)

    _, verify_s = run(
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

    return {
        "co_split_input_s": split_input_s,
        "co_generate_witness_wall_s": max(witness_times.values()),
        "co_generate_witness_party0_s": witness_times["co_generate_witness_party0"],
        "co_generate_witness_party1_s": witness_times["co_generate_witness_party1"],
        "co_generate_witness_party2_s": witness_times["co_generate_witness_party2"],
        "mpc_witness_proof_status": "ok",
        "mpc_witness_proof_s": max(proof_times.values()),
        "co_split_witness_s": 0.0,
        "co_prove_wall_s": max(proof_times.values()),
        "co_prove_party0_s": proof_times["generated_witness_proof_party0"],
        "co_prove_party1_s": proof_times["generated_witness_proof_party1"],
        "co_prove_party2_s": proof_times["generated_witness_proof_party2"],
        "co_verify_s": verify_s,
    }


def file_size(path: str) -> int:
    return (WORK / path).stat().st_size


def artifact_sizes() -> dict[str, int]:
    return {
        "r1cs_bytes": file_size("blindcert_lr4.r1cs"),
        "zkey_bytes": file_size("blindcert_lr4.zkey"),
        "verification_key_bytes": file_size("verification_key.json"),
        "single_proof_bytes": file_size("single_proof.json"),
        "collaborative_proof_bytes": file_size("collaborative_proof.json"),
        "public_input_bytes": file_size("collaborative_public.json"),
        "witness_bytes": file_size("witness.wtns"),
        "witness_share0_bytes": file_size("witness.wtns.0.shared"),
    }


def summarize(records: list[dict[str, Any]], setup: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"setup": setup, "metrics": {}}
    keys = sorted({k for row in records for k, v in row.items() if isinstance(v, int | float) and k != "iteration"})
    for key in keys:
        values = [float(row[key]) for row in records if isinstance(row.get(key), int | float)]
        if not values:
            continue
        summary["metrics"][key] = {
            "mean": statistics.mean(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
            "n": len(values),
        }
    statuses = sorted({str(row.get("mpc_witness_proof_status")) for row in records if row.get("mpc_witness_proof_status")})
    summary["mpc_witness_proof_statuses"] = statuses
    return summary


def write_csv(summary: dict[str, Any]) -> None:
    path = WORK / "efficiency_summary.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "mean", "stdev", "min", "max", "n"])
        for key, payload in summary["metrics"].items():
            writer.writerow([key, payload["mean"], payload["stdev"], payload["min"], payload["max"], payload["n"]])


def latex_num(value: float, digits: int = 3) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}"


def write_latex(summary: dict[str, Any]) -> None:
    m = summary["metrics"]
    s = summary["setup"]
    rows = [
        ("Circuit constraints", float(s["constraints"]), "--"),
        ("Circuit wires", float(s["wires"]), "--"),
        ("MP-SPDZ online time (s)", m["mpspdz_online_s"]["mean"], m["mpspdz_online_s"]["stdev"]),
        ("MP-SPDZ wall time (s)", m["mpspdz_wall_s"]["mean"], m["mpspdz_wall_s"]["stdev"]),
        ("MP-SPDZ communication (MB)", m["mpspdz_communication_bytes"]["mean"] / 1_000_000, m["mpspdz_communication_bytes"]["stdev"] / 1_000_000),
        ("Single-prover witness (s)", m["single_witness_s"]["mean"], m["single_witness_s"]["stdev"]),
        ("Single-prover Groth16 prove (s)", m["single_prove_s"]["mean"], m["single_prove_s"]["stdev"]),
        ("Single-prover Groth16 verify (s)", m["single_verify_s"]["mean"], m["single_verify_s"]["stdev"]),
        ("Collaborative input sharing (s)", m["co_split_input_s"]["mean"], m["co_split_input_s"]["stdev"]),
        ("Collaborative witness generation wall time (s)", m["co_generate_witness_wall_s"]["mean"], m["co_generate_witness_wall_s"]["stdev"]),
        ("Collaborative Groth16 prove wall time (s)", m["co_prove_wall_s"]["mean"], m["co_prove_wall_s"]["stdev"]),
        ("Collaborative Groth16 verify (s)", m["co_verify_s"]["mean"], m["co_verify_s"]["stdev"]),
        ("Proof size (KB)", float(s["collaborative_proof_bytes"]) / 1024, "--"),
        ("Verification key size (KB)", float(s["verification_key_bytes"]) / 1024, "--"),
    ]
    lines = [
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"Metric & Mean & Std. dev. \\",
        r"\midrule",
    ]
    for name, mean, stdev in rows:
        stdev_text = stdev if isinstance(stdev, str) else latex_num(float(stdev))
        lines.append(f"{name} & {latex_num(float(mean))} & {stdev_text} \\\\")
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    (WORK / "efficiency_table.tex").write_text("\n".join(lines), encoding="utf-8")


def write_notes(summary: dict[str, Any], iterations: int) -> None:
    m = summary["metrics"]
    s = summary["setup"]
    note = f"""# BlindCert efficiency results

Protocol instance: LR-4 demo relation derived from the paper protocol. The circuit binds the model commitment,
benchmark digest, policy digest, challenge/sample digest, session identifier, and policy pass bit.

Runs: {iterations}

Key values suitable for an experimental-efficiency table:

- Constraints: {s["constraints"]}
- Wires: {s["wires"]}
- Private inputs: {s["private_inputs"]}
- Public outputs: {s["public_outputs"]}
- MP-SPDZ online time: {m["mpspdz_online_s"]["mean"]:.4f} ± {m["mpspdz_online_s"]["stdev"]:.4f} s
- MP-SPDZ communication: {m["mpspdz_communication_bytes"]["mean"] / 1_000_000:.3f} MB
- Single-prover Groth16 proving: {m["single_prove_s"]["mean"]:.4f} ± {m["single_prove_s"]["stdev"]:.4f} s
- Single-prover Groth16 verification: {m["single_verify_s"]["mean"]:.4f} ± {m["single_verify_s"]["stdev"]:.4f} s
- Collaborative witness generation wall time: {m["co_generate_witness_wall_s"]["mean"]:.4f} ± {m["co_generate_witness_wall_s"]["stdev"]:.4f} s
- Collaborative Groth16 proving wall time: {m["co_prove_wall_s"]["mean"]:.4f} ± {m["co_prove_wall_s"]["stdev"]:.4f} s
- Collaborative Groth16 verification: {m["co_verify_s"]["mean"]:.4f} ± {m["co_verify_s"]["stdev"]:.4f} s
- Collaborative proof size: {s["collaborative_proof_bytes"] / 1024:.2f} KB
- Verification key size: {s["verification_key_bytes"] / 1024:.2f} KB

Important limitation: this legacy component experiment does not implement a continuous MASCOT-to-REP3
certification session. It must not populate system efficiency tables. Proof generation fails immediately if
co-circom cannot use the generated witness shares; there is no plaintext-witness fallback.

Generated files:

- `efficiency_raw.jsonl`: per-run raw metrics
- `efficiency_summary.json`: aggregate metrics
- `efficiency_summary.csv`: CSV table
- `efficiency_table.tex`: LaTeX table
"""
    (WORK / "README.md").write_text(note, encoding="utf-8")


def write_raw(records: Iterable[dict[str, Any]]) -> None:
    with (WORK / "efficiency_raw.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BlindCert efficiency measurements.")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--legacy-component-benchmark", action="store_true")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--attempt-mpc-witness-proof", action="store_true")
    args = parser.parse_args()
    if args.config or args.preflight:
        script = "preflight_system_efficiency.py" if args.preflight else "run_system_efficiency.py"
        command = [os.sys.executable, str(ROOT / "scripts" / script)]
        if args.config:
            command.extend(["--config", str(args.config)])
        if args.output:
            command.extend(["--output", str(args.output)])
        if not args.preflight:
            command.extend(["--iterations", str(args.iterations)])
        return subprocess.run(command, check=False).returncode
    if not args.legacy_component_benchmark:
        parser.error("use --config configs/system_efficiency.yaml --preflight; the legacy path requires --legacy-component-benchmark")
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")

    require_tools()
    prepare_dirs(clean=args.clean)
    configs = write_party_configs()
    write_input()
    circuit_metrics, setup_times = compile_and_setup()

    records: list[dict[str, Any]] = []
    for i in range(args.iterations):
        row: dict[str, Any] = {"iteration": i}
        row.update(run_single_prover())
        row.update(run_mpspdz())
        row.update(run_collaborative(configs, attempt_mpc_witness_proof=args.attempt_mpc_witness_proof))
        records.append(row)
        write_raw(records)

    setup: dict[str, Any] = {}
    setup.update(circuit_metrics)
    setup.update(setup_times)
    setup.update(artifact_sizes())
    setup["toolchain"] = {
        "mpspdz": "0.4.3 release",
        "co_circom": "0.9.0 release",
        "circom": "2.2.3 release",
        "snarkjs": "0.7.6",
    }
    summary = summarize(records, setup)
    (WORK / "efficiency_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    write_csv(summary)
    write_latex(summary)
    write_notes(summary, args.iterations)
    print(json.dumps({"status": "ok", "results_dir": str(WORK), "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
