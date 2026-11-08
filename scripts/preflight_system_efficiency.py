from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def capture(command: list[str]) -> dict:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return {"command": command, "returncode": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "error": str(exc)}


def parameter_count(model: dict) -> int:
    layers = model["layers"]
    if model["kind"] == "polynomial_svm":
        dimension = layers[0]
        return 1 + dimension + dimension * (dimension + 1) // 2
    return sum((a + 1) * b for a, b in zip(layers, layers[1:]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Record readiness; never run component benchmarks.")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/system_efficiency.yaml")
    parser.add_argument("--toolchain-root", type=Path, default=ROOT / "external")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    required = {"mpc_backend": "mpspdz", "mpc_protocol": "mascot", "mpc_parties": 3,
                "proof_backend": "collaborative", "proof_protocol": "REP3",
                "proof_system": "groth16", "proof_parties": 3, "holders": 2, "strata": 2}
    for key, expected in required.items():
        if config.get(key) != expected:
            parser.error(f"{key} must be {expected!r}")
    if not 0 < config["sample_size"] <= config["population_size"]:
        parser.error("sample_size must be positive and at most population_size")
    if config["sample_size"] % 2 or config["iterations"] != 1:
        parser.error("two equal strata and one measured session are required")
    output = args.output or ROOT / config["output_dir"]
    output.mkdir(parents=True, exist_ok=True)
    toolchain = args.toolchain_root.resolve()
    tools = {"circom": toolchain / "circom", "co_circom": toolchain / "co-circom",
             "mascot": toolchain / "mp-spdz-0.4.3/mascot-party.x",
             "node": toolchain / "node-v24.18.0-linux-x64/bin/node",
             "snarkjs": toolchain / "node_modules/.bin/snarkjs"}
    blockers = [
        "MASCOT returns an execution descriptor instead of authenticated witness shares.",
        "BN254 MAC-checked resharing to REP3 is not implemented or validated.",
        "Complete certification circuits and public statement binding are not implemented.",
        "Independent public verification and closed-interval timing are not implemented.",
        "Quantization bounds and feasible statistical policy are not yet validated.",
    ]
    missing = [name for name, path in tools.items() if not os.access(path, os.X_OK)]
    if missing:
        blockers.append("Missing executables: " + ", ".join(missing))
    environment = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "cpu_count": os.cpu_count(), "disk": shutil.disk_usage(output)._asdict(),
        "cpu": capture(["lscpu"]), "memory": capture(["free", "-b"]),
        "host_information": "Only guest-visible information is available.",
        "source_commit": capture(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
        "tools": {name: {"path": str(path), "exists": path.exists()}
                  for name, path in tools.items()},
        "versions": {name: capture([str(tools[name]), "--version"])
                     for name in ("circom", "co_circom", "node") if tools[name].exists()},
    }
    manifest = [{**model, "parameter_count": parameter_count(model),
                 "status": "NOT_IMPLEMENTED", "constraints": None, "private_inputs": None}
                for model in config["models"]]
    report = {"status": "NOT_IMPLEMENTED", "measurement_started": False,
              "blockers": blockers, "models": manifest,
              "iteration_decision": "One session, following the explicit instruction in section 1."}
    for name, value in (("environment.json", environment), ("model_manifest.json", manifest),
                        ("preflight.json", report)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    (output / "effective_config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    print(json.dumps({"status": report["status"], "output": str(output), "blockers": blockers}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
