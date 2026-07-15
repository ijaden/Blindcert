from __future__ import annotations

from blindcert.hashing import hash_obj
from blindcert.types import (
    ProofKeys,
    ProofResult,
    ProvingKey,
    PublicStatement,
    RelationConfig,
    VerificationKey,
    WitnessShare,
)


class MockProofBackend:
    """Insecure proof test double for plumbing and passport binding."""

    backend_id = "mock"

    def setup(self, relation_config: RelationConfig) -> ProofKeys:
        key_id = hash_obj("mock_proof_key_v1", {"backend": self.backend_id, "config": relation_config})
        return ProofKeys(ProvingKey(self.backend_id, key_id), VerificationKey(self.backend_id, key_id))

    def _proof(self, key_id: str, public_statement: PublicStatement) -> str:
        return hash_obj(
            "mock_public_proof_v1",
            {"backend": self.backend_id, "key_id": key_id, "statement": public_statement},
        )

    def prove(
        self,
        proving_key: ProvingKey,
        public_statement: PublicStatement,
        witness_shares: list[WitnessShare],
    ) -> ProofResult:
        if proving_key.backend_id != self.backend_id:
            return ProofResult(None, None, None, None, None, False, self.backend_id, {"error": "bad key"})
        if not witness_shares:
            return ProofResult(None, None, None, None, None, False, self.backend_id, {"error": "no witness"})
        proof = self._proof(proving_key.key_id, public_statement)
        return ProofResult(
            proof=proof,
            proof_seconds=None,
            proof_size_bytes=len(proof.encode("utf-8")),
            communication_bytes=None,
            peak_memory_bytes=None,
            success=True,
            backend_id=self.backend_id,
            raw_logs={"status": "mocked", "insecure": True},
        )

    def verify(
        self,
        verification_key: VerificationKey,
        public_statement: PublicStatement,
        proof: bytes | str,
    ) -> bool:
        if verification_key.backend_id != self.backend_id:
            return False
        return proof == self._proof(verification_key.key_id, public_statement)
