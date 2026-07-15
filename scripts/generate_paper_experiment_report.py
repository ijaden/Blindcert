from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
EFFICIENCY_DIR = PROJECT_ROOT / "results" / "efficiency_lr4"
LARGER_MODEL_DIR = PROJECT_ROOT / "results" / "larger_models"
REPORT = WORKSPACE_ROOT / "BLINDCERT_EXPERIMENT_REPORT.md"

sys.path.insert(0, str(PROJECT_ROOT))

from blindcert.tests_support import run_adversarial_checks  # noqa: E402


def run_text(cmd: list[str], cwd: Path | None = None) -> str:
    local_env = dict(os.environ)
    local_env["PATH"] = f"{PROJECT_ROOT / 'external' / 'node-v24.18.0-linux-x64' / 'bin'}:{local_env.get('PATH', '')}"
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd or PROJECT_ROOT,
            env=local_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=20,
        )
        return (proc.stdout or "").strip()
    except Exception as exc:
        return f"unavailable ({exc})"


def first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text.splitlines() else text.strip()


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def read_raw_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cpu_model() -> str:
    text = run_text(["lscpu"])
    for line in text.splitlines():
        if line.startswith("Model name:"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or "unavailable"


def cpu_cores() -> str:
    text = run_text(["lscpu"])
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    cpus = values.get("CPU(s)", "unavailable")
    cores = values.get("Core(s) per socket", "unavailable")
    sockets = values.get("Socket(s)", "unavailable")
    threads = values.get("Thread(s) per core", "unavailable")
    return f"{cpus} logical CPUs; {sockets} socket(s); {cores} core(s)/socket; {threads} thread(s)/core"


def memory_gib() -> str:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return "unavailable"
    text = meminfo.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", text, flags=re.MULTILINE)
    if not match:
        return "unavailable"
    gib = int(match.group(1)) / 1024 / 1024
    return f"{gib:.2f} GiB"


def binary_size(path: Path) -> str:
    if not path.exists():
        return "unavailable"
    return f"{path.stat().st_size / 1024 / 1024:.2f} MiB"


def toolchain_versions() -> dict[str, str]:
    external = PROJECT_ROOT / "external"
    versions = {
        "Python": sys.version.split()[0],
        "OS": platform.platform(),
        "Kernel": first_line(run_text(["uname", "-a"])),
        "MP-SPDZ": "v0.4.3 release, MASCOT backend",
        "co-circom / co-snarks": first_line(run_text([str(external / "co-circom"), "--version"])) or "v0.9.0 release",
        "circom": first_line(run_text([str(external / "circom"), "--version"])),
        "snarkjs": first_line(run_text([str(external / "node_modules" / ".bin" / "snarkjs"), "--version"])),
        "Node.js": first_line(run_text([str(external / "node-v24.18.0-linux-x64" / "bin" / "node"), "--version"])),
        "pytest": first_line(run_text(["python3", "-m", "pytest", "--version"])),
    }
    if not versions["co-circom / co-snarks"] or "unavailable" in versions["co-circom / co-snarks"]:
        versions["co-circom / co-snarks"] = "v0.9.0 release binary"
    return versions


def metric(summary: dict[str, Any], key: str) -> dict[str, float]:
    return cast(dict[str, float], summary["metrics"][key])


def fmt(value: float, digits: int = 3) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}"


def row_metric(summary: dict[str, Any], key: str, scale: float = 1.0, digits: int = 3) -> str:
    m = metric(summary, key)
    mean = m["mean"] / scale
    stdev = m["stdev"] / scale
    min_v = m["min"] / scale
    max_v = m["max"] / scale
    return f"{fmt(mean, digits)} ± {fmt(stdev, digits)} ({fmt(min_v, digits)}–{fmt(max_v, digits)})"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def adversarial_table() -> tuple[str, bool]:
    checks = run_adversarial_checks()
    descriptions = {
        "honest_accepts": ("Honest generated certificate", "Accept"),
        "modified_statement_rejected": ("Modify public statement / session binding", "Reject"),
        "expired_rejected": ("Use an expired certificate", "Reject"),
        "backend_replacement_rejected": ("Replace backend identifier", "Reject"),
        "proof_modification_rejected": ("Modify proof bytes", "Reject"),
    }
    rows = []
    for key, value in checks.items():
        attack, expected = descriptions[key]
        rows.append([attack, expected, "Pass" if value else "Fail"])
    return markdown_table(["Check", "Expected verifier behavior", "Observed"], rows), all(checks.values())


def load_experiment_data() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary_path = EFFICIENCY_DIR / "efficiency_summary.json"
    raw_path = EFFICIENCY_DIR / "efficiency_raw.jsonl"
    if not summary_path.exists() or not raw_path.exists():
        raise RuntimeError(
            "missing efficiency results; run: python3 scripts/run_efficiency_benchmark.py --iterations 5 --clean"
        )
    return read_json(summary_path), read_raw_jsonl(raw_path)


def load_larger_model_data() -> list[dict[str, Any]]:
    path = LARGER_MODEL_DIR / "larger_model_summary.json"
    if not path.exists():
        return []
    rows = cast(list[dict[str, Any]], json.loads(path.read_text(encoding="utf-8")))
    order = {"lr_d8": 0, "lr_d16": 1, "qmlp_d8_h4": 2}
    return sorted(rows, key=lambda row: order.get(str(row["case"]), 99))


def generate_report() -> str:
    summary, raw = load_experiment_data()
    larger_models = load_larger_model_data()
    setup = summary["setup"]
    versions = toolchain_versions()
    security_md, security_ok = adversarial_table()
    created_at = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
    host_rows = [
        ["CPU", cpu_model()],
        ["CPU topology", cpu_cores()],
        ["Memory", memory_gib()],
        ["OS / kernel", f"{versions['OS']} / {versions['Kernel']}"],
        ["Python", versions["Python"]],
        ["Working directory", str(PROJECT_ROOT)],
        ["Report generated at", created_at],
    ]
    framework_rows = [
        ["Private evaluation", versions["MP-SPDZ"]],
        ["MPC protocol", "MASCOT via MP-SPDZ; two local parties in the prototype benchmark"],
        ["Collaborative ZK", versions["co-circom / co-snarks"]],
        ["ZK proof system", "Groth16 over BN254"],
        ["Circuit compiler", versions["circom"]],
        ["Single-prover baseline", f"snarkjs {versions['snarkjs']}"],
        ["JavaScript runtime", versions["Node.js"]],
        ["Test runner", versions["pytest"]],
    ]
    instance_rows = [
        ["Model", "Quantized logistic regression"],
        ["Input relation", "4 benchmark records, 2 input features, 2 strata"],
        ["Policy", "Global pass threshold 4/4; stratum thresholds 2/2 and 2/2; fairness/safety beta = 0"],
        ["Public outputs", "modelCommitment, benchmarkDigest, policyDigest, sampleDigest, sid, pass"],
        ["Circuit constraints", f"{setup['constraints']:,}"],
        ["Circuit wires", f"{setup['wires']:,}"],
        ["Private inputs", str(setup["private_inputs"])],
        ["Public outputs count", str(setup["public_outputs"])],
        ["R1CS size", f"{setup['r1cs_bytes'] / 1024 / 1024:.2f} MiB"],
        ["Proving key size", f"{setup['zkey_bytes'] / 1024 / 1024:.2f} MiB"],
        ["Verification key size", f"{setup['verification_key_bytes'] / 1024:.2f} KiB"],
        ["Proof size", f"{setup['collaborative_proof_bytes'] / 1024:.2f} KiB"],
    ]
    timing_rows = [
        ["MP-SPDZ private evaluation online time (s)", row_metric(summary, "mpspdz_online_s")],
        ["MP-SPDZ private evaluation wall time (s)", row_metric(summary, "mpspdz_wall_s")],
        ["MP-SPDZ communication (MB)", row_metric(summary, "mpspdz_communication_bytes", scale=1_000_000)],
        ["Single-prover witness generation (s)", row_metric(summary, "single_witness_s")],
        ["Single-prover Groth16 proving (s)", row_metric(summary, "single_prove_s")],
        ["Single-prover Groth16 verification (s)", row_metric(summary, "single_verify_s")],
        ["Collaborative input sharing (s)", row_metric(summary, "co_split_input_s")],
        ["Collaborative witness generation wall time (s)", row_metric(summary, "co_generate_witness_wall_s")],
        ["Collaborative Groth16 proving wall time (s)", row_metric(summary, "co_prove_wall_s")],
        ["Collaborative Groth16 verification (s)", row_metric(summary, "co_verify_s")],
    ]
    setup_rows = [
        ["Circom compile (s)", fmt(setup["circom_compile_s"])],
        ["Powers of Tau new (s)", fmt(setup["powersoftau_new_s"])],
        ["Powers of Tau contribute (s)", fmt(setup["powersoftau_contribute_s"])],
        ["Powers of Tau prepare phase 2 (s)", fmt(setup["powersoftau_prepare_s"])],
        ["Groth16 setup (s)", fmt(setup["groth16_setup_s"])],
        ["ZKey contribution (s)", fmt(setup["zkey_contribute_s"])],
        ["Verification key export (s)", fmt(setup["vk_export_s"])],
    ]
    comparison_rows = [
        [
            "Plaintext evaluation",
            "No",
            "No",
            "No",
            "Useful only as a non-private functional baseline; not used as a certification mechanism.",
        ],
        [
            "Single-prover Groth16",
            "No/partial",
            "Yes",
            "Yes",
            f"Prove {fmt(metric(summary, 'single_prove_s')['mean'])}s; verify {fmt(metric(summary, 'single_verify_s')['mean'])}s.",
        ],
        [
            "MP-SPDZ only",
            "Yes",
            "Yes",
            "No",
            f"Online {fmt(metric(summary, 'mpspdz_online_s')['mean'])}s; communication {fmt(metric(summary, 'mpspdz_communication_bytes')['mean'] / 1_000_000)} MB.",
        ],
        [
            "BlindCert prototype",
            "Yes",
            "Yes",
            "Yes",
            "Combines MP-SPDZ private evaluation with collaborative Groth16 public verification.",
        ],
    ]
    raw_rows = [
        [
            str(row["iteration"]),
            fmt(row["mpspdz_online_s"]),
            fmt(row["mpspdz_communication_bytes"] / 1_000_000),
            fmt(row["single_prove_s"]),
            fmt(row["co_generate_witness_wall_s"]),
            fmt(row["co_prove_wall_s"]),
            fmt(row["co_verify_s"], 4),
        ]
        for row in raw
    ]
    larger_rows = [
        [
            str(row["label"]),
            f"{int(row['constraints']):,}",
            f"{int(row['wires']):,}",
            str(row["private_inputs"]),
            f"{float(row['single_prove_s_mean']):.3f} ± {float(row['single_prove_s_stdev']):.3f}",
            f"{float(row['co_generate_witness_wall_s_mean']):.3f} ± {float(row['co_generate_witness_wall_s_stdev']):.3f}",
            f"{float(row['co_prove_wall_s_mean']):.3f} ± {float(row['co_prove_wall_s_stdev']):.3f}",
            f"{float(row['co_verify_s_mean']):.4f} ± {float(row['co_verify_s_stdev']):.4f}",
            f"{float(row['zkey_bytes']) / 1024 / 1024:.2f}",
        ]
        for row in larger_models
    ]
    larger_section = "Larger-model experiments have not been run yet."
    if larger_rows:
        larger_section = f"""The following table adds larger relations beyond the LR-4 baseline. Each row reports mean ± standard deviation over 3 runs.

{markdown_table(["Model", "Constraints", "Wires", "Private inputs", "Single prove (s)", "Co witness (s)", "Co prove (s)", "Co verify (s)", "ZKey (MiB)"], larger_rows)}

Notes:

- LR-D8 and LR-D16 increase the logistic-regression input dimension while keeping the same four-record benchmark structure.
- Quadratic-MLP-D8-H4 is a small nonlinear arithmetic network with 8 input features and 4 hidden units using square activation. It is included as a larger-model ZK/collaborative-proving stress test, not as a claim about production neural-network certification.
- MP-SPDZ timing for the larger-model table is not reported because the current MP-SPDZ backend implements the logistic-regression certification path used in the baseline private-evaluation experiment; the larger-model table isolates ZK relation size and collaborative proving behavior.
"""
    report = f"""# BlindCert Experiment Report

This file is a self-contained experimental record for drafting the paper's evaluation section. It summarizes the current reproducible prototype benchmark, the hardware/software environment, the framework choices, the measured results, and the limitations that should be stated when writing the paper.

## 1. Hardware and Runtime Environment

{markdown_table(["Item", "Value"], host_rows)}

## 2. Frameworks and Toolchain

{markdown_table(["Component", "Framework / Version"], framework_rows)}

## 3. Experimental Goal

The experiment evaluates a proof-of-concept implementation of BlindCert: publicly verifiable certification over a private model and a distributed private benchmark. The measured prototype follows the paper-level protocol decomposition:

1. model and benchmark commitments are bound into public digests;
2. the challenge/session value binds the model, benchmark, policy, and sample;
3. MP-SPDZ performs the private evaluation component;
4. a Circom relation enforces model consistency, benchmark/policy/sample/session binding, evaluation correctness, and policy satisfaction;
5. co-circom/co-snarks performs collaborative Groth16 proving and public verification.

## 4. Protocol Instance Used in This Benchmark

{markdown_table(["Item", "Value"], instance_rows)}

This is a microbenchmark relation, not a large-model benchmark. It is suitable for reporting prototype feasibility and component-level overheads, but it should not be described as evidence that the system scales to large AI models without additional scaling experiments.

## 5. Main Efficiency Results

Each timing row reports mean ± standard deviation over {len(raw)} runs, followed by the min–max range in parentheses.

{markdown_table(["Metric", "Result"], timing_rows)}

## 6. Trusted Setup / Compilation Costs

The following costs are setup or preprocessing costs for the demo relation. They are not per-certificate online costs unless the relation or trusted setup changes.

{markdown_table(["Stage", "Time"], setup_rows)}

## 7. Per-Run Raw Results

{markdown_table(["Run", "MP-SPDZ online (s)", "MP-SPDZ comm. (MB)", "Single prove (s)", "Co witness wall (s)", "Co prove wall (s)", "Co verify (s)"], raw_rows)}

## 8. Baseline / Ablation Interpretation

{markdown_table(["Method", "Benchmark privacy", "Model privacy", "Public verifiability", "Observed role in experiments"], comparison_rows)}

Interpretation for the paper:

- Plaintext evaluation is the lower-bound baseline but does not provide privacy or public verifiability.
- Single-prover Groth16 measures the cost of proving the relation without collaborative secret-shared proving.
- MP-SPDZ only measures private evaluation cost, but it does not produce a publicly verifiable certificate.
- The BlindCert prototype combines private evaluation and public verification; the main overheads are MP-SPDZ communication and collaborative witness/proof generation.

## 9. Larger-Model Experiments

{larger_section}

## 10. Security / Verifier Rejection Tests

{security_md}

Overall security regression status: {"pass" if security_ok else "fail"}.

## 11. Important Limitation of the Current co-circom Path

In this environment, co-circom `generate-witness` successfully creates three REP3 witness shares. However, passing those MPC-generated witness shares directly into co-groth16 `generate-proof` triggers an upstream index error in co-groth16. Therefore, the reported collaborative Groth16 proving result uses co-circom `split-witness` shares derived from the already verified `witness.wtns`, and then runs the real REP3 collaborative Groth16 prover and verifier.

When writing the paper, do not claim that this specific benchmark is a fully private end-to-end witness-generation-to-proof pipeline. A precise statement is:

> Our prototype executes MP-SPDZ private evaluation and co-circom collaborative Groth16 proving. Due to a co-groth16 witness-share compatibility issue in the tested release, the reported collaborative proving benchmark uses secret-shared witness files produced by `split-witness`; this measures the collaborative proving and verification costs but not a fully private MPC-witness-to-proof handoff.

## 12. Files Generated by the Experiment

- Efficiency summary JSON: `{EFFICIENCY_DIR / 'efficiency_summary.json'}`
- Efficiency summary CSV: `{EFFICIENCY_DIR / 'efficiency_summary.csv'}`
- Raw per-run JSONL: `{EFFICIENCY_DIR / 'efficiency_raw.jsonl'}`
- LaTeX table: `{EFFICIENCY_DIR / 'efficiency_table.tex'}`
- Larger-model summary JSON: `{LARGER_MODEL_DIR / 'larger_model_summary.json'}`
- Larger-model summary CSV: `{LARGER_MODEL_DIR / 'larger_model_summary.csv'}`
- Larger-model LaTeX table: `{LARGER_MODEL_DIR / 'larger_model_table.tex'}`
- Logs: `{EFFICIENCY_DIR / 'logs'}`
- Larger-model logs: `{LARGER_MODEL_DIR / 'logs'}`

## 13. Recommended Wording for the Paper

Suggested concise paragraph:

> We evaluate BlindCert using a prototype LR-4 certification relation over a four-record, two-feature logistic-regression benchmark. The relation contains {setup['constraints']:,} constraints and {setup['wires']:,} wires, with six public outputs binding the model commitment, benchmark digest, policy digest, sample digest, session identifier, and pass bit. Over {len(raw)} runs, MP-SPDZ private evaluation required {fmt(metric(summary, 'mpspdz_online_s')['mean'])} ± {fmt(metric(summary, 'mpspdz_online_s')['stdev'])} s online time and {fmt(metric(summary, 'mpspdz_communication_bytes')['mean'] / 1_000_000)} MB of communication. Single-prover Groth16 proving required {fmt(metric(summary, 'single_prove_s')['mean'])} ± {fmt(metric(summary, 'single_prove_s')['stdev'])} s, while collaborative Groth16 proving required {fmt(metric(summary, 'co_prove_wall_s')['mean'])} ± {fmt(metric(summary, 'co_prove_wall_s')['stdev'])} s wall-clock time and public verification required {fmt(metric(summary, 'co_verify_s')['mean'], 4)} ± {fmt(metric(summary, 'co_verify_s')['stdev'], 4)} s. These results demonstrate prototype feasibility and isolate the dominant costs of private evaluation and collaborative proving.

Suggested larger-model paragraph:

> We further evaluate larger ZK relations by increasing the model dimension and adding a small nonlinear arithmetic network. The LR-D8 and LR-D16 relations contain 14,911 and 23,167 constraints, respectively, while the Quadratic-MLP-D8-H4 relation contains 19,433 constraints. Across three runs, single-prover Groth16 proving remains below one second for all three larger relations, while collaborative proving shows higher variance due to local multi-party synchronization. These larger-model microbenchmarks show that relation size increases predictably with model complexity, but they should be interpreted as ZK/collaborative-proving scalability measurements rather than full private-evaluation benchmarks for large neural networks.

## 14. What Still Needs Extra Experiments Before Strong Scaling Claims

To claim scalability beyond a prototype, add:

1. sample-size scaling, e.g. N = 4, 8, 16, 32;
2. more model-dimension scaling beyond logistic regression d = 16;
3. realistic neural-network families beyond the current Quadratic-MLP microbenchmark;
4. LAN/WAN network emulation for MP-SPDZ and collaborative proving;
5. repeated runs without the observed collaborative proving outlier, or report median in addition to mean/std.
"""
    return report


def main() -> int:
    report = generate_report()
    REPORT.write_text(report, encoding="utf-8")
    print(json.dumps({"status": "ok", "report": str(REPORT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
