from __future__ import annotations

import os
import json
import sys
import uuid
import subprocess
import time
from pathlib import Path

from blindcert.bridge.mpspdz_rep3 import SCALAR_FIELD
from blindcert.mpc.parsers import parse_communication_bytes, parse_policy_pass, parse_time_seconds
from blindcert.types import MPCConfig, MPCResult, PublicStatement, Share, WitnessShare


class MPSPDZBackend:
    backend_id = "mpspdz"

    def __init__(self) -> None:
        self.root: Path | None = None
        self.protocol = "mascot"
        self.party_count = 3
        self.timeout_s = 3600
        self.work_dir = Path(__file__).resolve().parents[2] / "results/mpspdz"

    def setup(self, config: MPCConfig) -> None:
        if config.party_count != 3 or config.protocol not in ("mascot", "mock"):
            raise ValueError("this backend requires three MASCOT parties")
        if config.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.party_count = config.party_count
        self.timeout_s = config.timeout_s
        if config.work_dir:
            self.work_dir = Path(config.work_dir).resolve()
        root = os.environ.get("MPSPDZ_ROOT")
        bundled = Path(__file__).resolve().parents[2] / "external" / "mp-spdz-0.4.3"
        candidate = Path(root) if root else bundled
        if not candidate.exists():
            raise RuntimeError(
                "MP-SPDZ unavailable: set MPSPDZ_ROOT or run scripts/install_mpspdz_release.py"
            )
        if not (candidate / "Scripts" / "compile-run.py").exists():
            raise RuntimeError(f"MP-SPDZ unavailable: missing Scripts/compile-run.py under {candidate}")
        if not (candidate / "mascot-party.x").exists():
            raise RuntimeError(
                f"MP-SPDZ unavailable: missing mascot-party.x under {candidate}; run Scripts/tldr.sh"
            )
        self.root = candidate
        self.protocol = config.protocol if config.protocol != "mock" else "mascot"

    def _write_logistic_program(
        self,
        program_name: str,
        dimension: int,
        strata_for_records: list[str],
        policy,
        record_owners: list[int],
    ) -> None:
        assert self.root is not None
        source = self.root / "Programs" / "Source" / f"{program_name}.mpc"
        source.parent.mkdir(parents=True, exist_ok=True)
        stratum_ids = sorted(policy.strata)
        lines = [
            "from Compiler.library import check_point",
            f"D = {dimension}",
            f"N = {len(strata_for_records)}",
            "weights = Array(D, sint)",
            "for i in range(D):",
            "    weights[i] = sint.get_input_from(0)",
            "bias = sint.get_input_from(0)",
            "exported = [weights[i] for i in range(D)] + [bias]",
            "correct = sint(0)",
            "violations = sint(0)",
        ]
        for g in stratum_ids:
            safe_g = g.replace("-", "_")
            lines.append(f"correct_{safe_g} = sint(0)")
            lines.append(f"total_{safe_g} = 0")
        for idx, stratum in enumerate(strata_for_records):
            safe_g = stratum.replace("-", "_")
            owner = record_owners[idx]
            lines.append("acc = bias")
            for j in range(dimension):
                lines.append(f"x_{idx}_{j} = sint.get_input_from({owner})")
                lines.append(f"acc += weights[{j}] * x_{idx}_{j}")
                lines.append(f"exported.append(x_{idx}_{j})")
            lines.append(f"y = sint.get_input_from({owner})")
            lines.append(f"attribute = sint.get_input_from({owner})")
            lines.append("pred = acc >= 0")
            lines.append("exported.extend([y, attribute, pred])")
            lines.append("is_correct = pred == y")
            lines.append("correct += is_correct")
            lines.append(f"correct_{safe_g} += is_correct")
            lines.append(f"total_{safe_g} += 1")
            lines.append("violations += (attribute == 1) * pred")
        checks = [
            f"(correct * {policy.tau_all_den} >= {policy.tau_all_num * len(strata_for_records)})",
            f"(violations * {policy.beta_den} <= {policy.beta_num})",
        ]
        for g in stratum_ids:
            safe_g = g.replace("-", "_")
            sp = policy.strata[g]
            checks.append(f"(correct_{safe_g} * {sp.tau_den} >= {sp.tau_num} * total_{safe_g})")
        lines.append("passed = " + " * ".join(checks))
        lines.append("print_ln('BLINDCERT_MPC_POLICY_PASS=%s', passed.reveal())")
        lines.extend([
            "for value in exported:",
            "    masked = value + sint.get_random()",
            "    print_ln('BLINDCERT_MASKED=%s', masked.reveal())",
            "check_point()",
            "sint.write_to_file(exported, position=0)",
            "check_point()",
            "print_ln('BLINDCERT_MAC_CHECK_COMPLETE')",
        ])
        source.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_inputs(self, opening, witness_records: list, directories: list[Path], owners: list[int]) -> None:
        assert self.root is not None
        player_data = directories[0] / "Player-Data"
        player_data.mkdir(exist_ok=True)
        params = opening.parameters
        weights = [int(v) for v in params["weights"]]
        bias = int(params.get("bias", 0))
        (player_data / "Input-P0-0").write_text(
            " ".join(str(v) for v in [*weights, bias]) + "\n",
            encoding="utf-8",
        )
        holder_values: dict[int, list[int]] = {1: [], 2: []}
        for wr, owner in zip(witness_records, owners):
            record = wr.record
            if not isinstance(record.x, list) or not record.x or isinstance(record.x[0], list):
                raise ValueError("MPSPDZBackend logistic path expects flat integer records")
            holder_values[owner].extend(int(v) for v in record.x)
            holder_values[owner].append(int(record.y))
            holder_values[owner].append(-1 if record.attribute is None else int(record.attribute))
        for owner in (1, 2):
            (directories[owner] / f"Player-Data/Input-P{owner}-0").write_text(
                " ".join(str(v) for v in holder_values[owner]) + "\n", encoding="utf-8")

    def evaluate(
        self,
        public_statement: PublicStatement,
        model_shares: list[Share],
        benchmark_shares: list[Share],
    ) -> MPCResult:
        if self.root is None:
            self.setup(MPCConfig(self.backend_id, "mascot"))
        assert self.root is not None
        if not model_shares or not benchmark_shares:
            raise ValueError("MPSPDZBackend requires model and benchmark shares")
        opening = model_shares[0].value
        if opening.arch_id != "logistic_regression":
            raise NotImplementedError("MPSPDZBackend currently implements logistic_regression only")
        payload = benchmark_shares[0].value
        policy = payload["policy"]
        witness_records = payload["witness_records"]
        if not witness_records:
            raise ValueError("no sampled witness records supplied")
        first_x = witness_records[0].record.x
        if not isinstance(first_x, list) or not first_x or isinstance(first_x[0], list):
            raise ValueError("MPSPDZBackend logistic path expects flat integer records")
        dimension = len(first_x)
        holders = sorted({wr.record.holder_id for wr in witness_records})
        if len(holders) != 2:
            raise ValueError("exactly two data holders are required")
        owners = [holders.index(wr.record.holder_id) + 1 for wr in witness_records]
        run_dir = self.work_dir / uuid.uuid4().hex
        run_dir.mkdir(parents=True, mode=0o700)
        directories = [run_dir / f"party{i}" for i in range(3)]
        for directory in directories:
            (directory / "Player-Data").mkdir(parents=True)
            (directory / "Programs").symlink_to(self.root.resolve() / "Programs", target_is_directory=True)
        program_name = "blindcert_lr_" + run_dir.name
        self._write_logistic_program(
            program_name,
            dimension,
            [wr.record.stratum_id for wr in witness_records],
            policy,
            owners,
        )
        self._write_inputs(opening, witness_records, directories, owners)
        start = time.perf_counter()
        compile_proc = subprocess.run(
            [sys.executable, "compile.py", "-F", "64", program_name], cwd=self.root,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=self.timeout_s, check=False)
        (run_dir / "compile.log").write_text(compile_proc.stdout)
        if compile_proc.returncode:
            raise RuntimeError(f"MASCOT compilation failed; see {run_dir / 'compile.log'}")
        processes = []
        logs = []
        deadline = time.monotonic() + self.timeout_s
        try:
            for i, directory in enumerate(directories):
                output = (directory / "mascot.log").open("w")
                try:
                    processes.append(subprocess.Popen(
                        [str(self.root.resolve() / "mascot-party.x"), "-N", "3",
                         "-P", str(SCALAR_FIELD), "-pn", "15630", "-h", "127.0.0.1",
                         "-p", str(i), program_name], cwd=directory,
                        stdout=output, stderr=subprocess.STDOUT))
                finally:
                    output.close()
            codes = [p.wait(timeout=max(.01, deadline - time.monotonic())) for p in processes]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        logs = [(directory / "mascot.log").read_text() for directory in directories]
        elapsed = time.perf_counter() - start
        log = "\n".join(logs)
        returncode = next((code for code in codes if code), 0)
        if "BLINDCERT_MAC_CHECK_COMPLETE" not in logs[0]:
            returncode = returncode or 1
        pass_bit = parse_policy_pass(log)
        if returncode != 0 or pass_bit is None:
            return MPCResult(
                ok=False,
                witness_shares=[],
                preprocessing_seconds=None,
                online_seconds=parse_time_seconds(log) or elapsed,
                communication_bytes=parse_communication_bytes(log),
                peak_memory_bytes=None,
                raw_logs={
                    "backend": self.backend_id,
                    "protocol": self.protocol,
                    "party_count": self.party_count,
                    "party_exit_codes": codes,
                    "run_directory": str(run_dir),
                    "returncode": returncode,
                    "stdout": log,
                },
            )
        return MPCResult(
            ok=pass_bit,
            witness_shares=[
                WitnessShare({
                    "kind": "mpspdz_authenticated_bn254_inputs_and_predictions",
                    "path": str(directory / f"Persistence/Transactions-P{i}.data"),
                    "party": i,
                    "field": str(SCALAR_FIELD),
                    "count": dimension + 1 + len(witness_records) * (dimension + 3),
                    "mac_checked": True,
                    "sid": public_statement.sid,
                }) for i, directory in enumerate(directories)
            ],
            preprocessing_seconds=None,
            online_seconds=parse_time_seconds(log) or elapsed,
            communication_bytes=parse_communication_bytes(log),
            peak_memory_bytes=None,
            raw_logs={
                "backend": self.backend_id,
                "protocol": self.protocol,
                    "party_count": self.party_count,
                    "party_exit_codes": codes,
                    "run_directory": str(run_dir),
                "returncode": returncode,
                "stdout": log,
            },
        )
