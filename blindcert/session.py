from __future__ import annotations

import time
from dataclasses import dataclass

from blindcert.commitment import commit_model
from blindcert.datasets.tabular import synthetic_binary_tabular
from blindcert.merkle import register_benchmark
from blindcert.mpc.mock_backend import MockMPCBackend
from blindcert.mpc.mpspdz_backend import MPSPDZBackend
from blindcert.policy import policy_id
from blindcert.proofs.mock_backend import MockProofBackend
from blindcert.protocol.challenge import build_transcript
from blindcert.protocol.model_factory import model_from_opening
from blindcert.protocol.prove import generate_passport
from blindcert.protocol.verify import verify_passport
from blindcert.protocol.witness import witness_records_for_sample
from blindcert.sampling import stratified_sample
from blindcert.types import (
    CertificationPolicy,
    MPCConfig,
    Passport,
    PublicStatement,
    PublicTranscript,
    QuantizationSpec,
    RelationConfig,
    Share,
    StratumPolicy,
    VerificationKey,
)


@dataclass(frozen=True)
class EndToEndResult:
    passport: Passport
    transcript: PublicTranscript
    verification_key: VerificationKey
    verified: bool


@dataclass(frozen=True)
class MPCDemoResult:
    ok: bool
    online_seconds: float | None
    communication_bytes: int | None


def demo_policy() -> CertificationPolicy:
    qspec = QuantizationSpec(scale_bits=0, value_bits=16, accumulator_bits=48)
    return CertificationPolicy(
        cid="demo-certification",
        arch_id="logistic_regression",
        qspec=qspec,
        strata={
            "g0": StratumPolicy(32, 8, 7, 8, 0.05),
            "g1": StratumPolicy(32, 8, 7, 8, 0.05),
        },
        tau_all_num=7,
        tau_all_den=8,
        beta_num=16,
        beta_den=1,
        safe_predicate_id="default_no_positive_for_attribute_1",
    )


def _normalize_policy(policy: CertificationPolicy) -> CertificationPolicy:
    strata = {
        k: (v if isinstance(v, StratumPolicy) else StratumPolicy(**v))
        for k, v in policy.strata.items()
    }
    return CertificationPolicy(
        policy.cid,
        policy.arch_id,
        policy.qspec,
        strata,
        policy.tau_all_num,
        policy.tau_all_den,
        policy.beta_num,
        policy.beta_den,
        policy.safe_predicate_id,
    )


def run_demo_end_to_end(expiry: int | None = None) -> EndToEndResult:
    policy = _normalize_policy(demo_policy())
    parameters = {"weights": [1, 1], "bias": 0}
    model_commitment, opening = commit_model(
        policy.arch_id, policy.qspec, parameters, randomness="00" * 32
    )
    records = synthetic_binary_tabular(holder_count=2, per_holder_stratum=16)
    registry = register_benchmark(records)
    parties = ["owner", "h0", "h1"]
    sid = "sid-demo"
    transcript, seed = build_transcript(
        sid,
        parties,
        policy,
        registry.digest,
        registry.partition_sizes,
        fixed_openings={"owner": "01" * 32, "h0": "02" * 32, "h1": "03" * 32},
    )
    sampled = stratified_sample(seed, policy, registry.partition_sizes)
    public_statement = PublicStatement(
        sid=sid,
        pid=policy_id(policy),
        cid=policy.cid,
        model_commitment=model_commitment,
        benchmark_digest=registry.digest,
        seed=seed,
        sampled_indices=sampled,
    )
    witness_records = witness_records_for_sample(registry, sampled)
    model = model_from_opening(opening)
    mpc = MockMPCBackend()
    mpc.setup(MPCConfig("mock"))
    mpc_result = mpc.evaluate(
        public_statement,
        [Share(opening)],
        [Share({"model": model, "policy": policy, "witness_records": witness_records})],
    )
    proof_backend = MockProofBackend()
    keys = proof_backend.setup(RelationConfig("mock"))
    passport = generate_passport(
        proof_backend,
        keys.proving_key,
        public_statement,
        mpc_result.witness_shares,
        policy,
        expiry=expiry or int(time.time()) + 3600,
    )
    if passport is None:
        raise RuntimeError("honest certification failed")
    verified = verify_passport(transcript, policy, keys.verification_key, passport, int(time.time()))
    return EndToEndResult(passport, transcript, keys.verification_key, verified)


def run_demo_mpspdz_evaluation() -> MPCDemoResult:
    policy = _normalize_policy(demo_policy())
    parameters = {"weights": [1, 1], "bias": 0}
    model_commitment, opening = commit_model(
        policy.arch_id, policy.qspec, parameters, randomness="00" * 32
    )
    records = synthetic_binary_tabular(holder_count=2, per_holder_stratum=16)
    registry = register_benchmark(records)
    sampled = stratified_sample("mpspdz-demo-seed", policy, registry.partition_sizes)
    public_statement = PublicStatement(
        sid="sid-mpspdz-demo",
        pid=policy_id(policy),
        cid=policy.cid,
        model_commitment=model_commitment,
        benchmark_digest=registry.digest,
        seed="mpspdz-demo-seed",
        sampled_indices=sampled,
    )
    witness_records = witness_records_for_sample(registry, sampled)
    backend = MPSPDZBackend()
    backend.setup(MPCConfig("mpspdz", "mascot"))
    result = backend.evaluate(
        public_statement,
        [Share(opening)],
        [Share({"policy": policy, "witness_records": witness_records})],
    )
    return MPCDemoResult(result.ok, result.online_seconds, result.communication_bytes)
