from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from blindcert.hashing import hash_obj
from blindcert.serialization import canonical_json
from blindcert.types import (
    ProofKeys,
    ProofResult,
    ProvingKey,
    PublicStatement,
    RelationConfig,
    VerificationKey,
    WitnessShare,
)


class CollaborativeProofBackend:
    backend_id = "collaborative"

    def __init__(self) -> None:
        self.config: RelationConfig | None = None
        self.co_circom: Path | None = None

    def _resolve_binary(self, relation_config: RelationConfig) -> Path:
        configured = relation_config.co_circom_path or os.environ.get("CO_CIRCOM")
        bundled = Path(__file__).resolve().parents[2] / "external" / "co-circom"
        candidate = Path(configured) if configured else bundled
        if not candidate.exists():
            raise RuntimeError(
                "co-circom unavailable: set CO_CIRCOM or run scripts/install_co_circom_release.py"
            )
        return candidate

    def setup(self, relation_config: RelationConfig) -> ProofKeys:
        self.co_circom = self._resolve_binary(relation_config)
        self.config = relation_config
        payload = {
            "backend": self.backend_id,
            "proof_system": relation_config.proof_system,
            "curve": relation_config.curve,
            "protocol": relation_config.protocol,
            "zkey_path": relation_config.zkey_path,
            "verification_key_path": relation_config.verification_key_path,
            "network_config_paths": relation_config.network_config_paths,
        }
        key_id = canonical_json(payload)
        key_hash = hash_obj("collaborative_proof_key_v1", payload)
        return ProofKeys(
            ProvingKey(self.backend_id, key_id),
            VerificationKey(self.backend_id, canonical_json({**payload, "key_hash": key_hash})),
        )

    def prove(
        self,
        proving_key: ProvingKey,
        public_statement: PublicStatement,
        witness_shares: list[WitnessShare],
    ) -> ProofResult:
        if self.config is None or self.co_circom is None:
            self.setup(RelationConfig(self.backend_id))
        assert self.config is not None
        assert self.co_circom is not None
        if proving_key.backend_id != self.backend_id:
            return ProofResult(None, None, None, None, None, False, self.backend_id, {"error": "bad key"})
        if not self.config.zkey_path:
            return ProofResult(
                None,
                None,
                None,
                None,
                None,
                False,
                self.backend_id,
                {"status": "missing_artifact", "missing": "zkey_path"},
            )
        shares = [share.value for share in witness_shares]
        if not shares or not all(isinstance(s, dict) and "witness" in s and "config" in s for s in shares):
            return ProofResult(
                None,
                None,
                None,
                None,
                None,
                False,
                self.backend_id,
                {
                    "status": "missing_artifact",
                    "expected_witness_share": {"witness": "path", "config": "network_config.toml"},
                },
            )
        work_dir = Path(self.config.work_dir or "results/collaborative")
        work_dir.mkdir(parents=True, exist_ok=True)
        proof_path = work_dir / f"{public_statement.sid}.proof.json"
        public_input_path = work_dir / f"{public_statement.sid}.public.json"
        processes: list[subprocess.Popen[str]] = []
        start = time.perf_counter()
        for i, share in enumerate(shares):
            cmd = [
                str(self.co_circom),
                "generate-proof",
                self.config.proof_system,
                "--config",
                str(share["config"]),
                "--witness",
                str(share["witness"]),
                "--zkey",
                str(self.config.zkey_path),
                "--protocol",
                self.config.protocol,
                "--curve",
                self.config.curve,
            ]
            if i == 0:
                cmd.extend(["--out", str(proof_path), "--public-input", str(public_input_path)])
            processes.append(
                subprocess.Popen(
                    cmd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            )
        logs: list[str] = []
        returncode = 0
        for proc in processes:
            stdout, _ = proc.communicate()
            logs.append(stdout or "")
            returncode = returncode or proc.returncode
        elapsed = time.perf_counter() - start
        if returncode != 0 or not proof_path.exists() or not public_input_path.exists():
            return ProofResult(
                None,
                elapsed,
                None,
                None,
                None,
                False,
                self.backend_id,
                {"status": "co_circom_failed", "returncode": returncode, "logs": logs},
            )
        proof_bundle = {
            "proof": json.loads(proof_path.read_text(encoding="utf-8")),
            "public_input": json.loads(public_input_path.read_text(encoding="utf-8")),
            "proof_system": self.config.proof_system,
            "curve": self.config.curve,
        }
        proof_text = json.dumps(proof_bundle, sort_keys=True, separators=(",", ":"))
        return ProofResult(
            proof=proof_text,
            proof_seconds=elapsed,
            proof_size_bytes=len(proof_text.encode("utf-8")),
            communication_bytes=None,
            peak_memory_bytes=None,
            success=True,
            backend_id=self.backend_id,
            raw_logs={"status": "real_co_circom", "logs": logs},
        )

    def verify(
        self,
        verification_key: VerificationKey,
        public_statement: PublicStatement,
        proof: bytes | str,
    ) -> bool:
        if verification_key.backend_id != self.backend_id:
            return False
        try:
            key_payload = json.loads(verification_key.key_id)
            proof_bundle = json.loads(proof.decode("utf-8") if isinstance(proof, bytes) else proof)
        except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        co_circom = self._resolve_binary(
            RelationConfig(self.backend_id, co_circom_path=key_payload.get("co_circom_path"))
        )
        vk = key_payload.get("verification_key_path")
        if not vk:
            return False
        work_dir = Path(
            self.config.work_dir if self.config and self.config.work_dir else "results/collaborative"
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        proof_path = work_dir / f"{public_statement.sid}.verify.proof.json"
        public_input_path = work_dir / f"{public_statement.sid}.verify.public.json"
        proof_path.write_text(json.dumps(proof_bundle["proof"]), encoding="utf-8")
        public_input_path.write_text(json.dumps(proof_bundle["public_input"]), encoding="utf-8")
        proc = subprocess.run(
            [
                str(co_circom),
                "verify",
                proof_bundle.get("proof_system", key_payload.get("proof_system", "groth16")),
                "--proof",
                str(proof_path),
                "--curve",
                proof_bundle.get("curve", key_payload.get("curve", "BN254")),
                "--vk",
                str(vk),
                "--public-input",
                str(public_input_path),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return proc.returncode == 0
