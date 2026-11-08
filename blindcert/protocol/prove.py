from __future__ import annotations

from blindcert.proofs.relation import check_relation
from blindcert.types import (
    CertificationPolicy,
    Passport,
    ProvingKey,
    PublicStatement,
    WitnessShare,
    Witness,
)


def generate_passport(
    backend,
    proving_key: ProvingKey,
    public_statement: PublicStatement,
    witness_shares: list[WitnessShare],
    policy: CertificationPolicy,
    expiry: int,
) -> Passport | None:
    if not witness_shares:
        return None
    witness = witness_shares[0].value
    if not isinstance(witness, Witness):
        return None
    if not check_relation(public_statement, witness, policy):
        return None
    result = backend.prove(proving_key, public_statement, witness_shares)
    if not result.success or result.proof is None:
        return None
    return Passport(public_statement, result.proof, expiry, result.backend_id)
