from __future__ import annotations

from typing import Protocol

from blindcert.types import (
    ProofKeys,
    ProofResult,
    PublicStatement,
    RelationConfig,
    VerificationKey,
    ProvingKey,
    WitnessShare,
)


class ProofBackend(Protocol):
    backend_id: str

    def setup(self, relation_config: RelationConfig) -> ProofKeys: ...

    def prove(
        self,
        proving_key: ProvingKey,
        public_statement: PublicStatement,
        witness_shares: list[WitnessShare],
    ) -> ProofResult: ...

    def verify(
        self,
        verification_key: VerificationKey,
        public_statement: PublicStatement,
        proof: bytes | str,
    ) -> bool: ...
