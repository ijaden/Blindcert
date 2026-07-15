from __future__ import annotations

import argparse
import csv
import json
import math
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
WORK = ROOT / "results" / "larger_models"


def env() -> dict[str, str]:
    out = dict(os.environ)
    out["PATH"] = f"{NODE_BIN}:{out.get('PATH', '')}"
    return out


def run(cmd: list[str], cwd: Path, check: bool = True) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    elapsed = time.perf_counter() - started
    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    stem = "_".join(Path(part).name for part in cmd[:3])
    (WORK / "logs" / f"{int(time.time() * 1000)}_{stem}.log").write_text(proc.stdout or "", encoding="utf-8")
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed with exit {proc.returncode}: {' '.join(cmd)}\n{proc.stdout[-4000:]}")
    return proc, elapsed


def start(cmd: list[str], cwd: Path) -> tuple[subprocess.Popen[str], float]:
    return (
        subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ),
        time.perf_counter(),
    )


def wait_all(procs: list[tuple[str, subprocess.Popen[str], float]]) -> dict[str, float]:
    times: dict[str, float] = {}
    failures: list[tuple[str, int]] = []
    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    for name, proc, started in procs:
        stdout, _ = proc.communicate()
        times[name] = time.perf_counter() - started
        (WORK / "logs" / f"{name}.log").write_text(stdout or "", encoding="utf-8")
        if proc.returncode != 0:
            failures.append((name, proc.returncode))
    if failures:
        raise RuntimeError(f"parallel commands failed: {failures}")
    return times


def require_tools() -> None:
    for path in [SNARKJS, CIRCOM, CO_CIRCOM, NODE_BIN / "node"]:
        if not path.exists():
            raise RuntimeError(f"missing required tool: {path}")


def prepare(clean: bool) -> None:
    if clean and WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "logs").mkdir(exist_ok=True)
    (WORK / "ptau").mkdir(exist_ok=True)


def copy_support_files(case_dir: Path) -> None:
    (case_dir / "lib").mkdir(parents=True, exist_ok=True)
    (case_dir / "configs").mkdir(exist_ok=True)
    (case_dir / "data").mkdir(exist_ok=True)
    for source in (CO_EXAMPLES / "lib").glob("*.circom"):
        shutil.copy2(source, case_dir / "lib" / source.name)
    for name in ["cert0.der", "cert1.der", "cert2.der", "key0.der", "key1.der", "key2.der"]:
        shutil.copy2(CO_EXAMPLES / "data" / name, case_dir / "data" / name)


def party_configs(case_dir: Path, base_port: int) -> list[Path]:
    configs = []
    for i in range(3):
        config = case_dir / "configs" / f"party{i}.toml"
        config.write_text(
            f"""[compiler]
allow_leaky_loops = false
link_library = ["{case_dir / 'lib'}"]

[vm]
allow_leaky_logs = false

[network]
my_id = {i}
bind_addr = "0.0.0.0:{base_port + i}"
key_path = "{case_dir / 'data' / f'key{i}.der'}"

[[network.parties]]
id = 0
dns_name = "127.0.0.1:{base_port}"
cert_path = "{case_dir / 'data' / 'cert0.der'}"

[[network.parties]]
id = 1
dns_name = "127.0.0.1:{base_port + 1}"
cert_path = "{case_dir / 'data' / 'cert1.der'}"

[[network.parties]]
id = 2
dns_name = "127.0.0.1:{base_port + 2}"
cert_path = "{case_dir / 'data' / 'cert2.der'}"
""",
            encoding="utf-8",
        )
        configs.append(config)
    return configs


def common_signals(d: int) -> str:
    return f"""    var N = 4;
    var D = {d};
    var BITS = 32;

    signal input archId;
    signal input qScale;
    signal input threshold;
    signal input tauAllNum;
    signal input tauAllDen;
    signal input tau0Num;
    signal input tau0Den;
    signal input tau1Num;
    signal input tau1Den;
    signal input betaNum;
    signal input cid;
    signal input seed;
"""


def hash_chain(output: str, inputs: list[str], name: str, indent: str = "    ") -> str:
    if len(inputs) <= 16:
        lines = [f"{indent}component {name} = Poseidon({len(inputs)});"]
        for i, expr in enumerate(inputs):
            lines.append(f"{indent}{name}.inputs[{i}] <== {expr};")
        lines.append(f"{indent}{output} <== {name}.out;")
        return "\n".join(lines)
    chunks = [inputs[:16]]
    rest = inputs[16:]
    while rest:
        chunks.append(rest[:15])
        rest = rest[15:]
    lines = []
    prev = ""
    for idx, chunk in enumerate(chunks):
        component = f"{name}_{idx}"
        width = len(chunk) if idx == 0 else len(chunk) + 1
        lines.append(f"{indent}component {component} = Poseidon({width});")
        offset = 0
        if idx > 0:
            lines.append(f"{indent}{component}.inputs[0] <== {prev}.out;")
            offset = 1
        for i, expr in enumerate(chunk):
            lines.append(f"{indent}{component}.inputs[{i + offset}] <== {expr};")
        prev = component
    lines.append(f"{indent}{output} <== {prev}.out;")
    return "\n".join(lines)


def record_hash_block(d: int) -> tuple[str, list[str]]:
    record_inputs = [
        "holder[i]",
        "stratum[i]",
        "localIndex[i]",
        "nonce[i]",
        *[f"x[i][{j}]" for j in range(d)],
        "y[i]",
        "attribute[i]",
    ]
    if len(record_inputs) <= 16:
        lines = ["    component leaf[N];", "    for (var i = 0; i < N; i++) {", f"        leaf[i] = Poseidon({len(record_inputs)});"]
        for idx, expr in enumerate(record_inputs):
            lines.append(f"        leaf[i].inputs[{idx}] <== {expr};")
        lines.append("    }")
        return "\n".join(lines), [f"leaf[{i}].out" for i in range(4)]
    first = record_inputs[:16]
    rest = record_inputs[16:]
    lines = [
        "    component leaf0[N];",
        "    component leaf1[N];",
        "    for (var i = 0; i < N; i++) {",
        "        leaf0[i] = Poseidon(16);",
    ]
    for idx, expr in enumerate(first):
        lines.append(f"        leaf0[i].inputs[{idx}] <== {expr};")
    lines.append(f"        leaf1[i] = Poseidon({len(rest) + 1});")
    lines.append("        leaf1[i].inputs[0] <== leaf0[i].out;")
    for idx, expr in enumerate(rest):
        lines.append(f"        leaf1[i].inputs[{idx + 1}] <== {expr};")
    lines.append("    }")
    return "\n".join(lines), [f"leaf1[{i}].out" for i in range(4)]


def common_record_inputs(d: int) -> str:
    leaf_block, leaf_refs = record_hash_block(d)
    return f"""    signal input holder[N];
    signal input stratum[N];
    signal input localIndex[N];
    signal input nonce[N];
    signal input x[N][D];
    signal input y[N];
    signal input attribute[N];

    signal output modelCommitment;
    signal output benchmarkDigest;
    signal output policyDigest;
    signal output sampleDigest;
    signal output sid;
    signal output pass;

    component policyHash = Poseidon(11);
    policyHash.inputs[0] <== cid;
    policyHash.inputs[1] <== archId;
    policyHash.inputs[2] <== qScale;
    policyHash.inputs[3] <== threshold;
    policyHash.inputs[4] <== tauAllNum;
    policyHash.inputs[5] <== tauAllDen;
    policyHash.inputs[6] <== tau0Num;
    policyHash.inputs[7] <== tau0Den;
    policyHash.inputs[8] <== tau1Num;
    policyHash.inputs[9] <== tau1Den;
    policyHash.inputs[10] <== betaNum;
    policyDigest <== policyHash.out;

{leaf_block}

    component parent01 = Poseidon(2);
    parent01.inputs[0] <== {leaf_refs[0]};
    parent01.inputs[1] <== {leaf_refs[1]};
    component parent23 = Poseidon(2);
    parent23.inputs[0] <== {leaf_refs[2]};
    parent23.inputs[1] <== {leaf_refs[3]};
    component rootHash = Poseidon(2);
    rootHash.inputs[0] <== parent01.out;
    rootHash.inputs[1] <== parent23.out;
    benchmarkDigest <== rootHash.out;

    component sampleHash = Poseidon(5);
    sampleHash.inputs[0] <== seed;
    for (var i = 0; i < N; i++) {{
        sampleHash.inputs[i + 1] <== localIndex[i];
    }}
    sampleDigest <== sampleHash.out;
"""


def sid_hash_block() -> str:
    return """    component sidHash = Poseidon(5);
    sidHash.inputs[0] <== policyDigest;
    sidHash.inputs[1] <== modelCommitment;
    sidHash.inputs[2] <== benchmarkDigest;
    sidHash.inputs[3] <== sampleDigest;
    sidHash.inputs[4] <== seed;
    sid <== sidHash.out;
"""


def common_policy_checks() -> str:
    return """    correctAll <== correct[0] + correct[1] + correct[2] + correct[3];
    correct0 <== correct[0] + correct[1];
    correct1 <== correct[2] + correct[3];
    violations <== violation[0] + violation[1] + violation[2] + violation[3];

    component allOk = GreaterEqThan(BITS);
    allOk.in[0] <== correctAll * tauAllDen;
    allOk.in[1] <== tauAllNum * N;

    component g0Ok = GreaterEqThan(BITS);
    g0Ok.in[0] <== correct0 * tau0Den;
    g0Ok.in[1] <== tau0Num * 2;

    component g1Ok = GreaterEqThan(BITS);
    g1Ok.in[0] <== correct1 * tau1Den;
    g1Ok.in[1] <== tau1Num * 2;

    component betaOk = LessEqThan(BITS);
    betaOk.in[0] <== violations;
    betaOk.in[1] <== betaNum;

    passLeft <== allOk.out * g0Ok.out;
    passRight <== g1Ok.out * betaOk.out;
    pass <== passLeft * passRight;
    pass === 1;
"""


def lr_circuit(name: str, d: int) -> str:
    model_inputs = [
        "archId",
        "qScale",
        "threshold",
        *[f"theta[{j}]" for j in range(d)],
        "bias",
        "rTheta",
    ]
    model_hash = hash_chain("modelCommitment", model_inputs, "modelHash")
    return f"""pragma circom 2.0.0;

include "./lib/poseidon.circom";
include "./lib/comparators.circom";

template {name}() {{
{common_signals(d)}
    signal input theta[D];
    signal input bias;
    signal input rTheta;

{common_record_inputs(d)}
{model_hash}

{sid_hash_block()}

    signal score[N];
    signal prod[N][D];
    signal acc[N][D + 1];
    signal pred[N];
    signal correct[N];
    signal violation[N];
    signal correctAll;
    signal correct0;
    signal correct1;
    signal violations;
    signal passLeft;
    signal passRight;
    component lt[N];
    component eq[N];
    component xRange[N][D];

    for (var i = 0; i < N; i++) {{
        acc[i][0] <== bias;
        for (var j = 0; j < D; j++) {{
            xRange[i][j] = LessThan(BITS);
            xRange[i][j].in[0] <== x[i][j];
            xRange[i][j].in[1] <== 9;
            xRange[i][j].out === 1;
            prod[i][j] <== theta[j] * x[i][j];
            acc[i][j + 1] <== acc[i][j] + prod[i][j];
        }}
        y[i] * (y[i] - 1) === 0;
        attribute[i] * (attribute[i] - 1) === 0;
        score[i] <== acc[i][D];
        lt[i] = LessThan(BITS);
        lt[i].in[0] <== score[i];
        lt[i].in[1] <== threshold;
        pred[i] <== 1 - lt[i].out;
        eq[i] = IsEqual();
        eq[i].in[0] <== pred[i];
        eq[i].in[1] <== y[i];
        correct[i] <== eq[i].out;
        violation[i] <== attribute[i] * pred[i];
    }}

{common_policy_checks()}}}

component main = {name}();
"""


def mlp_quadratic_circuit(name: str, d: int, h: int) -> str:
    model_inputs = [
        "archId",
        "qScale",
        "threshold",
        *[f"w1[{k}][{j}]" for k in range(h) for j in range(d)],
        *[f"b1[{k}]" for k in range(h)],
        *[f"w2[{k}]" for k in range(h)],
        "b2",
        "rTheta",
    ]
    model_hash = hash_chain("modelCommitment", model_inputs, "modelHash")
    return f"""pragma circom 2.0.0;

include "./lib/poseidon.circom";
include "./lib/comparators.circom";

template {name}() {{
{common_signals(d)}
    var H = {h};
    signal input w1[H][D];
    signal input b1[H];
    signal input w2[H];
    signal input b2;
    signal input rTheta;

{common_record_inputs(d)}
{model_hash}

{sid_hash_block()}

    signal hiddenPre[N][H];
    signal hiddenSq[N][H];
    signal hiddenProd[N][H][D];
    signal hiddenAcc[N][H][D + 1];
    signal outProd[N][H];
    signal outAcc[N][H + 1];
    signal score[N];
    signal pred[N];
    signal correct[N];
    signal violation[N];
    signal correctAll;
    signal correct0;
    signal correct1;
    signal violations;
    signal passLeft;
    signal passRight;
    component lt[N];
    component eq[N];
    component xRange[N][D];

    for (var i = 0; i < N; i++) {{
        for (var j = 0; j < D; j++) {{
            xRange[i][j] = LessThan(BITS);
            xRange[i][j].in[0] <== x[i][j];
            xRange[i][j].in[1] <== 9;
            xRange[i][j].out === 1;
        }}
        for (var k = 0; k < H; k++) {{
            hiddenAcc[i][k][0] <== b1[k];
            for (var j = 0; j < D; j++) {{
                hiddenProd[i][k][j] <== w1[k][j] * x[i][j];
                hiddenAcc[i][k][j + 1] <== hiddenAcc[i][k][j] + hiddenProd[i][k][j];
            }}
            hiddenPre[i][k] <== hiddenAcc[i][k][D];
            hiddenSq[i][k] <== hiddenPre[i][k] * hiddenPre[i][k];
        }}
        outAcc[i][0] <== b2;
        for (var k = 0; k < H; k++) {{
            outProd[i][k] <== w2[k] * hiddenSq[i][k];
            outAcc[i][k + 1] <== outAcc[i][k] + outProd[i][k];
        }}
        y[i] * (y[i] - 1) === 0;
        attribute[i] * (attribute[i] - 1) === 0;
        score[i] <== outAcc[i][H];
        lt[i] = LessThan(BITS);
        lt[i].in[0] <== score[i];
        lt[i].in[1] <== threshold;
        pred[i] <== 1 - lt[i].out;
        eq[i] = IsEqual();
        eq[i].in[0] <== pred[i];
        eq[i].in[1] <== y[i];
        correct[i] <== eq[i].out;
        violation[i] <== attribute[i] * pred[i];
    }}

{common_policy_checks()}}}

component main = {name}();
"""


def stringify(value: Any) -> Any:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return [stringify(v) for v in value]
    return value


def input_for_variant(kind: str, d: int, h: int | None = None) -> dict[str, Any]:
    x = [
        [1] * d,
        [0] * d,
        [1] * max(1, d // 2) + [0] * (d - max(1, d // 2)),
        [1] + [0] * (d - 1),
    ]
    base: dict[str, Any] = {
        "archId": 2 if kind == "lr" else 3,
        "qScale": 0,
        "threshold": 3 if kind == "lr" else 9,
        "tauAllNum": 4,
        "tauAllDen": 4,
        "tau0Num": 2,
        "tau0Den": 2,
        "tau1Num": 2,
        "tau1Den": 2,
        "betaNum": 0,
        "cid": 202,
        "seed": 424242,
        "rTheta": 999,
        "holder": [1, 1, 2, 2],
        "stratum": [0, 0, 1, 1],
        "localIndex": [0, 1, 0, 1],
        "nonce": [1101, 1102, 2201, 2202],
        "x": x,
        "y": [1, 0, 1, 0],
        "attribute": [0, 0, 0, 1],
    }
    if kind == "lr":
        base["theta"] = [1] * d
        base["bias"] = 0
    else:
        assert h is not None
        base["w1"] = [[1] * d for _ in range(h)]
        base["b1"] = [0] * h
        base["w2"] = [1] * h
        base["b2"] = 0
    return {k: stringify(v) for k, v in base.items()}


def parse_r1cs_info(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
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
            out[key] = int(match.group(1))
    return out


def ensure_ptau(power: int) -> Path:
    final = WORK / "ptau" / f"pot{power}_final.ptau"
    if final.exists():
        return final
    p0 = WORK / "ptau" / f"pot{power}_0000.ptau"
    p1 = WORK / "ptau" / f"pot{power}_0001.ptau"
    run([str(SNARKJS), "powersoftau", "new", "bn128", str(power), str(p0), "-v"], cwd=WORK)
    run(
        [
            str(SNARKJS),
            "powersoftau",
            "contribute",
            str(p0),
            str(p1),
            "--name=blindcert-larger-models",
            "-v",
            "-e=blindcert larger models deterministic entropy",
        ],
        cwd=WORK,
    )
    run([str(SNARKJS), "powersoftau", "prepare", "phase2", str(p1), str(final), "-v"], cwd=WORK)
    return final


def setup_case(case_dir: Path, circuit_name: str) -> dict[str, Any]:
    proc, compile_s = run([str(CIRCOM), f"{circuit_name}.circom", "--r1cs", "--wasm", "--sym", "-o", str(case_dir)], cwd=case_dir)
    info_proc, r1cs_info_s = run([str(SNARKJS), "r1cs", "info", str(case_dir / f"{circuit_name}.r1cs")], cwd=case_dir)
    metrics = parse_r1cs_info(info_proc.stdout)
    power = max(14, math.ceil(math.log2(metrics["constraints"])))
    ptau = ensure_ptau(power)
    zkey0 = case_dir / f"{circuit_name}_0000.zkey"
    zkey = case_dir / f"{circuit_name}.zkey"
    _, setup_s = run([str(SNARKJS), "groth16", "setup", str(case_dir / f"{circuit_name}.r1cs"), str(ptau), str(zkey0)], cwd=case_dir)
    _, contribute_s = run(
        [
            str(SNARKJS),
            "zkey",
            "contribute",
            str(zkey0),
            str(zkey),
            "--name=blindcert-larger-model",
            "-v",
            "-e=blindcert larger model zkey entropy",
        ],
        cwd=case_dir,
    )
    _, vk_s = run([str(SNARKJS), "zkey", "export", "verificationkey", str(zkey), str(case_dir / "verification_key.json")], cwd=case_dir)
    return {
        **metrics,
        "ptau_power": power,
        "compile_s": compile_s,
        "r1cs_info_s": r1cs_info_s,
        "groth16_setup_s": setup_s,
        "zkey_contribute_s": contribute_s,
        "vk_export_s": vk_s,
    }


def single_prover(case_dir: Path, circuit_name: str) -> dict[str, float]:
    witness = case_dir / "witness.wtns"
    _, witness_s = run(
        [
            str(NODE_BIN / "node"),
            str(case_dir / f"{circuit_name}_js" / "generate_witness.js"),
            str(case_dir / f"{circuit_name}_js" / f"{circuit_name}.wasm"),
            str(case_dir / "input.json"),
            str(witness),
        ],
        cwd=case_dir,
    )
    _, prove_s = run(
        [
            str(SNARKJS),
            "groth16",
            "prove",
            str(case_dir / f"{circuit_name}.zkey"),
            str(witness),
            str(case_dir / "single_proof.json"),
            str(case_dir / "single_public.json"),
        ],
        cwd=case_dir,
    )
    _, verify_s = run(
        [
            str(SNARKJS),
            "groth16",
            "verify",
            str(case_dir / "verification_key.json"),
            str(case_dir / "single_public.json"),
            str(case_dir / "single_proof.json"),
        ],
        cwd=case_dir,
    )
    return {"single_witness_s": witness_s, "single_prove_s": prove_s, "single_verify_s": verify_s}


def collaborative(case_dir: Path, circuit_name: str, configs: list[Path]) -> dict[str, float]:
    _, split_input_s = run(
        [
            str(CO_CIRCOM),
            "split-input",
            "--circuit",
            str(case_dir / f"{circuit_name}.circom"),
            "--input",
            str(case_dir / "input.json"),
            "--protocol",
            "REP3",
            "--curve",
            "BN254",
            "--out-dir",
            str(case_dir),
            "--config",
            str(configs[0]),
        ],
        cwd=case_dir,
    )
    witness_procs = []
    for i, cfg in enumerate(configs):
        proc, started = start(
            [
                str(CO_CIRCOM),
                "generate-witness",
                "-O2",
                "--input",
                str(case_dir / f"input.json.{i}.shared"),
                "--circuit",
                str(case_dir / f"{circuit_name}.circom"),
                "--protocol",
                "REP3",
                "--curve",
                "BN254",
                "--config",
                str(cfg),
                "--out",
                str(case_dir / f"witness.wtns.{i}.shared"),
            ],
            cwd=case_dir,
        )
        witness_procs.append((f"{circuit_name}_co_witness_party{i}", proc, started))
    witness_times = wait_all(witness_procs)
    _, split_witness_s = run(
        [
            str(CO_CIRCOM),
            "split-witness",
            "--witness",
            str(case_dir / "witness.wtns"),
            "--r1cs",
            str(case_dir / f"{circuit_name}.r1cs"),
            "--protocol",
            "REP3",
            "--curve",
            "BN254",
            "--out-dir",
            str(case_dir),
        ],
        cwd=case_dir,
    )
    proof_procs = []
    for i, cfg in enumerate(configs):
        cmd = [
            str(CO_CIRCOM),
            "generate-proof",
            "groth16",
            "--witness",
            str(case_dir / f"witness.wtns.{i}.shared"),
            "--zkey",
            str(case_dir / f"{circuit_name}.zkey"),
            "--protocol",
            "REP3",
            "--curve",
            "BN254",
            "--config",
            str(cfg),
        ]
        if i == 0:
            cmd.extend(["--out", str(case_dir / "collaborative_proof.json"), "--public-input", str(case_dir / "collaborative_public.json")])
        proc, started = start(cmd, cwd=case_dir)
        proof_procs.append((f"{circuit_name}_co_proof_party{i}", proc, started))
    proof_times = wait_all(proof_procs)
    _, verify_s = run(
        [
            str(CO_CIRCOM),
            "verify",
            "groth16",
            "--proof",
            str(case_dir / "collaborative_proof.json"),
            "--vk",
            str(case_dir / "verification_key.json"),
            "--public-input",
            str(case_dir / "collaborative_public.json"),
            "--curve",
            "BN254",
        ],
        cwd=case_dir,
    )
    return {
        "co_split_input_s": split_input_s,
        "co_generate_witness_wall_s": max(witness_times.values()),
        "co_split_witness_s": split_witness_s,
        "co_prove_wall_s": max(proof_times.values()),
        "co_verify_s": verify_s,
    }


def artifact_sizes(case_dir: Path, circuit_name: str) -> dict[str, int]:
    return {
        "r1cs_bytes": (case_dir / f"{circuit_name}.r1cs").stat().st_size,
        "zkey_bytes": (case_dir / f"{circuit_name}.zkey").stat().st_size,
        "verification_key_bytes": (case_dir / "verification_key.json").stat().st_size,
        "single_proof_bytes": (case_dir / "single_proof.json").stat().st_size,
        "collaborative_proof_bytes": (case_dir / "collaborative_proof.json").stat().st_size,
        "witness_bytes": (case_dir / "witness.wtns").stat().st_size,
    }


def case_specs() -> list[dict[str, Any]]:
    return [
        {"case": "lr_d8", "label": "Logistic regression D=8", "kind": "lr", "d": 8},
        {"case": "lr_d16", "label": "Logistic regression D=16", "kind": "lr", "d": 16},
        {"case": "qmlp_d8_h4", "label": "Quadratic MLP D=8 H=4", "kind": "qmlp", "d": 8, "h": 4},
    ]


def write_raw(records: Iterable[dict[str, Any]]) -> None:
    with (WORK / "larger_model_raw.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def summarize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    order = {"lr_d8": 0, "lr_d16": 1, "qmlp_d8_h4": 2}
    for case in sorted({str(row["case"]) for row in records}, key=lambda value: order.get(value, 99)):
        rows = [row for row in records if row["case"] == case]
        first = rows[0]
        out: dict[str, Any] = {
            "case": case,
            "label": first["label"],
            "kind": first["kind"],
            "dimension": first["dimension"],
            "hidden": first.get("hidden"),
            "constraints": first["constraints"],
            "wires": first["wires"],
            "private_inputs": first["private_inputs"],
            "public_outputs": first["public_outputs"],
            "ptau_power": first["ptau_power"],
            "r1cs_bytes": first["r1cs_bytes"],
            "zkey_bytes": first["zkey_bytes"],
            "collaborative_proof_bytes": first["collaborative_proof_bytes"],
        }
        for key in [
            "single_witness_s",
            "single_prove_s",
            "single_verify_s",
            "co_generate_witness_wall_s",
            "co_prove_wall_s",
            "co_verify_s",
        ]:
            values = [float(row[key]) for row in rows]
            out[f"{key}_mean"] = statistics.mean(values)
            out[f"{key}_stdev"] = statistics.stdev(values) if len(values) > 1 else 0.0
            out[f"{key}_min"] = min(values)
            out[f"{key}_max"] = max(values)
        summary.append(out)
    return summary


def write_outputs(records: list[dict[str, Any]], summary: list[dict[str, Any]]) -> None:
    (WORK / "larger_model_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    with (WORK / "larger_model_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)
    lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Model & Constraints & Single prove (s) & Co witness (s) & Co prove (s) & Co verify (s) \\",
        r"\midrule",
    ]
    for row in summary:
        lines.append(
            f"{row['label']} & {int(row['constraints']):,} & "
            f"{row['single_prove_s_mean']:.3f} & {row['co_generate_witness_wall_s_mean']:.3f} & "
            f"{row['co_prove_wall_s_mean']:.3f} & {row['co_verify_s_mean']:.4f} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    (WORK / "larger_model_table.tex").write_text("\n".join(lines), encoding="utf-8")
    write_raw(records)


def run_case(spec: dict[str, Any], iteration: int) -> dict[str, Any]:
    case = str(spec["case"])
    circuit_name = f"blindcert_{case}"
    case_dir = WORK / case
    case_dir.mkdir(parents=True, exist_ok=True)
    copy_support_files(case_dir)
    configs = party_configs(case_dir, 12200 + 10 * case_specs().index(spec))
    d = int(spec["d"])
    h = spec.get("h")
    if spec["kind"] == "lr":
        source = lr_circuit(circuit_name, d)
    else:
        if h is None:
            raise ValueError(f"missing hidden size for {case}")
        source = mlp_quadratic_circuit(circuit_name, d, int(h))
    (case_dir / f"{circuit_name}.circom").write_text(source, encoding="utf-8")
    (case_dir / "input.json").write_text(
        json.dumps(input_for_variant(str(spec["kind"]), d, int(h) if h is not None else None), indent=2),
        encoding="utf-8",
    )

    setup_path = case_dir / "setup_metrics.json"
    if iteration == 0 or not setup_path.exists():
        setup = setup_case(case_dir, circuit_name)
        setup_path.write_text(json.dumps(setup, indent=2, sort_keys=True), encoding="utf-8")
    else:
        setup = json.loads(setup_path.read_text(encoding="utf-8"))
    single = single_prover(case_dir, circuit_name)
    co = collaborative(case_dir, circuit_name, configs)
    sizes = artifact_sizes(case_dir, circuit_name)
    return {
        "case": case,
        "label": spec["label"],
        "kind": spec["kind"],
        "dimension": d,
        "hidden": h,
        "iteration": iteration,
        **setup,
        **single,
        **co,
        **sizes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run larger-model BlindCert ZK/collaborative experiments.")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    require_tools()
    prepare(clean=args.clean)
    records: list[dict[str, Any]] = []
    for spec in case_specs():
        for iteration in range(args.iterations):
            records.append(run_case(spec, iteration))
            write_raw(records)
    summary = summarize(records)
    write_outputs(records, summary)
    print(json.dumps({"status": "ok", "results_dir": str(WORK), "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
