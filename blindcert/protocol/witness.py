from __future__ import annotations

from blindcert.merkle import BenchmarkRegistry
from blindcert.plaintext.evaluator import evaluate
from blindcert.policy import policy_id
from blindcert.protocol.model_factory import model_from_opening
from blindcert.types import GlobalIndex, ModelOpening, Witness, WitnessRecord, CertificationPolicy


def witness_records_for_sample(
    registry: BenchmarkRegistry, sampled_indices: dict[str, list[GlobalIndex]]
) -> list[WitnessRecord]:
    out: list[WitnessRecord] = []
    seen: set[tuple[str, str, int]] = set()
    for stratum_id in sorted(sampled_indices):
        for idx in sampled_indices[stratum_id]:
            key = (idx.holder_id, idx.stratum_id, idx.local_index)
            if key in seen:
                raise ValueError(f"duplicate sampled index: {key}")
            seen.add(key)
            record = registry.records[key]
            out.append(WitnessRecord(record=record, membership_proof=registry.membership_proof(record)))
    return out


def construct_witness(
    sid: str,
    policy: CertificationPolicy,
    opening: ModelOpening,
    witness_records: list[WitnessRecord],
) -> Witness:
    model = model_from_opening(opening)
    records = [wr.record for wr in witness_records]
    predictions, metrics = evaluate(model, records, policy)
    return Witness(opening, witness_records, predictions, metrics, policy_id(policy), sid)
