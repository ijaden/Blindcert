from __future__ import annotations

from blindcert.commitment import verify_model_commitment
from blindcert.merkle import verify_record_membership
from blindcert.plaintext.evaluator import evaluate
from blindcert.policy import evaluate_policy, policy_id
from blindcert.protocol.model_factory import model_from_opening
from blindcert.types import CertificationPolicy, PublicStatement, Witness


def check_relation(
    public_statement: PublicStatement,
    witness: Witness,
    policy: CertificationPolicy,
) -> bool:
    """Executable specification for the certified relation.

    This function intentionally sees the witness. It is used by tests and mock
    backends, not by public verification.
    """
    if witness.sid != public_statement.sid:
        return False
    if witness.policy_id != public_statement.pid or policy_id(policy) != public_statement.pid:
        return False
    if not verify_model_commitment(public_statement.model_commitment, witness.model_opening):
        return False
    if witness.model_opening.arch_id != policy.arch_id or witness.model_opening.qspec != policy.qspec:
        return False
    seen: set[tuple[str, str, int]] = set()
    records = []
    for wr in witness.records:
        key = (wr.record.holder_id, wr.record.stratum_id, wr.record.local_index)
        if key in seen:
            return False
        seen.add(key)
        if not verify_record_membership(wr.record, wr.membership_proof, public_statement.benchmark_digest):
            return False
        records.append(wr.record)
    sampled = {
        (idx.holder_id, idx.stratum_id, idx.local_index)
        for values in public_statement.sampled_indices.values()
        for idx in values
    }
    if sampled != seen:
        return False
    model = model_from_opening(witness.model_opening)
    predictions, metrics = evaluate(model, records, policy)
    if predictions != witness.predictions:
        return False
    if metrics.correct != witness.metrics.correct or metrics.violations != witness.metrics.violations:
        return False
    return evaluate_policy(policy, metrics)
