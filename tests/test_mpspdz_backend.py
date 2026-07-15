import os

from blindcert.commitment import commit_model
from blindcert.datasets.tabular import synthetic_binary_tabular
from blindcert.merkle import register_benchmark
from blindcert.mpc.mpspdz_backend import MPSPDZBackend
from blindcert.policy import policy_id
from blindcert.protocol.witness import witness_records_for_sample
from blindcert.sampling import stratified_sample
from blindcert.session import demo_policy
from blindcert.types import MPCConfig, PublicStatement, Share


def test_mpspdz_logistic_real_backend_when_installed() -> None:
    root = os.environ.get("MPSPDZ_ROOT")
    if root is None:
        candidate = os.path.join(os.path.dirname(__file__), "..", "external", "mp-spdz-0.4.3")
        if not os.path.exists(candidate):
            return
    policy = demo_policy()
    commitment, opening = commit_model(
        policy.arch_id, policy.qspec, {"weights": [1, 1], "bias": 0}, randomness="00" * 32
    )
    records = synthetic_binary_tabular(holder_count=2, per_holder_stratum=16)
    registry = register_benchmark(records)
    sampled = stratified_sample("mpspdz-test-seed", policy, registry.partition_sizes)
    statement = PublicStatement(
        "sid-mpspdz",
        policy_id(policy),
        policy.cid,
        commitment,
        registry.digest,
        "mpspdz-test-seed",
        sampled,
    )
    witness_records = witness_records_for_sample(registry, sampled)
    backend = MPSPDZBackend()
    backend.setup(MPCConfig("mpspdz", "mascot"))
    result = backend.evaluate(
        statement,
        [Share(opening)],
        [Share({"policy": policy, "witness_records": witness_records})],
    )
    assert result.ok
    assert result.online_seconds is not None
