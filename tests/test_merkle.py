from dataclasses import replace

from blindcert.datasets.tabular import synthetic_binary_tabular
from blindcert.merkle import register_benchmark, verify_record_membership


def test_two_level_merkle_rejects_changed_label() -> None:
    records = synthetic_binary_tabular(holder_count=1, strata=("g0",), per_holder_stratum=4)
    registry = register_benchmark(records)
    record = records[2]
    proof = registry.membership_proof(record)
    assert verify_record_membership(record, proof, registry.digest)
    changed = replace(record, y=1 - record.y)
    assert not verify_record_membership(changed, proof, registry.digest)


def test_duplicate_index_rejected() -> None:
    records = synthetic_binary_tabular(holder_count=1, strata=("g0",), per_holder_stratum=2)
    duplicate = replace(records[1], local_index=0)
    try:
        register_benchmark([records[0], duplicate])
    except ValueError:
        return
    raise AssertionError("duplicate index was accepted")
