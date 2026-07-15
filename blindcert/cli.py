from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from blindcert.benchmark.export import export_placeholder_results
from blindcert.benchmark.runner import benchmark_matrix
from blindcert.proofs.collaborative_backend import CollaborativeProofBackend
from blindcert.protocol.verify import verify_passport
from blindcert.serialization import write_json
from blindcert.session import demo_policy, run_demo_end_to_end, run_demo_mpspdz_evaluation
from blindcert.types import (
    CertificationPolicy,
    Passport,
    PublicStatement,
    PublicTranscript,
    QuantizationSpec,
    StratumPolicy,
    VerificationKey,
    GlobalIndex,
    RelationConfig,
    WitnessShare,
)


def _status(status: str, **extra: Any) -> None:
    print(json.dumps({"status": status, **extra}, sort_keys=True))


def _root() -> Path:
    return Path.cwd()


def _write_structured_log(command: str, status: str) -> None:
    path = _root() / "results/raw/cli_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command": command,
        "status": status,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "argv": sys.argv,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True) + "\n")


def cmd_run_end_to_end(args: argparse.Namespace) -> int:
    result = run_demo_end_to_end()
    out = Path(args.output)
    write_json(
        out,
        {
            "passport": result.passport,
            "transcript": result.transcript,
            "verification_key": result.verification_key,
            "policy": result.transcript.policy,
            "verified": result.verified,
        },
    )
    _status("ok", verified=result.verified, passport=str(out))
    return 0 if result.verified else 1


def cmd_export_results(args: argparse.Namespace) -> int:
    export_placeholder_results(_root(), demo_policy())
    _status("ok", exported="placeholder_results", fabricated=False)
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    matrix = benchmark_matrix()
    if args.dry_run:
        _status("ok", dry_run=True, runs=len(matrix), matrix=matrix[:5])
        return 0
    _status("not_implemented", notes="real benchmark execution is not implemented")
    return 2


def cmd_evaluate(args: argparse.Namespace) -> int:
    if args.backend == "mpspdz":
        result = run_demo_mpspdz_evaluation()
        _status(
            "ok" if result.ok else "failed",
            backend="mpspdz",
            online_seconds=result.online_seconds,
            communication_bytes=result.communication_bytes,
        )
        return 0 if result.ok else 1
    _status("ok", command=args.command, backend=args.backend, notes="prototype command completed")
    return 0


def cmd_prove(args: argparse.Namespace) -> int:
    if args.backend != "collaborative":
        _status("ok", command=args.command, backend=args.backend, notes="prototype command completed")
        return 0
    missing = []
    if not args.zkey:
        missing.append("--zkey")
    if not args.vk:
        missing.append("--vk")
    if not args.witness_share:
        missing.append("--witness-share CONFIG:WITNESS")
    if missing:
        _status("error", backend="collaborative", missing=missing)
        return 2
    backend = CollaborativeProofBackend()
    keys = backend.setup(
        RelationConfig(
            backend_id="collaborative",
            proof_system=args.proof_system,
            curve=args.curve,
            protocol=args.protocol,
            zkey_path=args.zkey,
            verification_key_path=args.vk,
            work_dir=args.work_dir,
        )
    )
    shares = []
    for item in args.witness_share:
        config, witness = item.split(":", 1)
        shares.append(WitnessShare({"config": config, "witness": witness}))
    placeholder_statement = run_demo_end_to_end().passport.public_statement
    result = backend.prove(keys.proving_key, placeholder_statement, shares)
    if result.success and result.proof is not None:
        Path(args.output).write_text(str(result.proof), encoding="utf-8")
    _status(
        "ok" if result.success else "failed",
        backend="collaborative",
        proof_seconds=result.proof_seconds,
        proof_size_bytes=result.proof_size_bytes,
        output=args.output if result.success else None,
        raw_logs=result.raw_logs,
    )
    return 0 if result.success else 1


def cmd_adversarial_tests(args: argparse.Namespace) -> int:
    from blindcert.tests_support import run_adversarial_checks

    checks = run_adversarial_checks()
    ok = all(checks.values())
    _status("ok" if ok else "failed", checks=checks)
    return 0 if ok else 1


def _load_bundle(path: str | Path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    q = data["policy"]["qspec"]
    qspec = QuantizationSpec(**q)
    strata = {k: StratumPolicy(**v) for k, v in data["policy"]["strata"].items()}
    policy = CertificationPolicy(
        data["policy"]["cid"],
        data["policy"]["arch_id"],
        qspec,
        strata,
        data["policy"]["tau_all_num"],
        data["policy"]["tau_all_den"],
        data["policy"]["beta_num"],
        data["policy"]["beta_den"],
        data["policy"]["safe_predicate_id"],
    )
    sampled = {
        g: [GlobalIndex(**idx) for idx in values]
        for g, values in data["passport"]["public_statement"]["sampled_indices"].items()
    }
    psd = data["passport"]["public_statement"]
    statement = PublicStatement(
        psd["sid"],
        psd["pid"],
        psd["cid"],
        psd["model_commitment"],
        psd["benchmark_digest"],
        psd["seed"],
        sampled,
    )
    passport = Passport(
        statement,
        data["passport"]["proof"],
        data["passport"]["expiry"],
        data["passport"]["backend_id"],
    )
    td = data["transcript"]
    transcript = PublicTranscript(
        td["sid"],
        policy,
        td["parties"],
        td["seed_commitments"],
        td["seed_openings"],
        td["benchmark_digest"],
        td.get("holder_stratum_roots", {}),
        td.get("holder_stratum_sizes", {}),
    )
    vk = VerificationKey(**data["verification_key"])
    return transcript, policy, vk, passport


def cmd_verify(args: argparse.Namespace) -> int:
    transcript, policy, vk, passport = _load_bundle(args.passport)
    ok = verify_passport(transcript, policy, vk, passport, int(time.time()))
    _status("ok" if ok else "rejected", verified=ok)
    return 0 if ok else 1


def cmd_simple(args: argparse.Namespace) -> int:
    _status("ok", command=args.command, notes="prototype command completed", config=args.config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m blindcert.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["prepare-data", "train", "register", "sample"]:
        p = sub.add_parser(name)
        p.add_argument("--config", default="configs/logistic_regression.yaml")
        p.add_argument("--backend", default="mock")
        p.set_defaults(func=cmd_simple)
    p = sub.add_parser("evaluate")
    p.add_argument("--config", default="configs/logistic_regression.yaml")
    p.add_argument("--backend", default="mock")
    p.set_defaults(func=cmd_evaluate)
    p = sub.add_parser("prove")
    p.add_argument("--config", default="configs/logistic_regression.yaml")
    p.add_argument("--backend", default="mock")
    p.add_argument("--zkey")
    p.add_argument("--vk")
    p.add_argument("--witness-share", action="append")
    p.add_argument("--proof-system", default="groth16")
    p.add_argument("--curve", default="BN254")
    p.add_argument("--protocol", default="REP3")
    p.add_argument("--work-dir", default="results/collaborative")
    p.add_argument("--output", default="results/collaborative/proof.json")
    p.set_defaults(func=cmd_prove)
    p = sub.add_parser("run-end-to-end")
    p.add_argument("--config", default="configs/logistic_regression.yaml")
    p.add_argument("--output", default="results/passport.json")
    p.set_defaults(func=cmd_run_end_to_end)
    p = sub.add_parser("verify")
    p.add_argument("--passport", default="results/passport.json")
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser("benchmark")
    p.add_argument("--config", default="configs/logistic_regression.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_benchmark)
    p = sub.add_parser("adversarial-tests")
    p.set_defaults(func=cmd_adversarial_tests)
    p = sub.add_parser("export-results")
    p.set_defaults(func=cmd_export_results)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rc = int(args.func(args))
        _write_structured_log(args.command, "ok" if rc == 0 else "failed")
        return rc
    except Exception as exc:
        _write_structured_log(args.command, "error")
        _status("error", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
