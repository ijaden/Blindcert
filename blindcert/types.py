from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class QuantizationSpec:
    scale_bits: int
    value_bits: int
    accumulator_bits: int
    rounding: str = "nearest"
    signed: bool = True


@dataclass(frozen=True)
class StratumPolicy:
    population_size: int
    sample_size: int
    tau_num: int
    tau_den: int
    epsilon: float


@dataclass(frozen=True)
class CertificationPolicy:
    cid: str
    arch_id: str
    qspec: QuantizationSpec
    strata: dict[str, StratumPolicy]
    tau_all_num: int
    tau_all_den: int
    beta_num: int
    beta_den: int
    safe_predicate_id: str


@dataclass(frozen=True)
class BenchmarkRecord:
    holder_id: str
    stratum_id: str
    local_index: int
    x: list[int] | list[list[int]]
    y: int
    attribute: int | None
    nonce: bytes


@dataclass(frozen=True)
class GlobalIndex:
    holder_id: str
    stratum_id: str
    local_index: int


@dataclass(frozen=True)
class PublicStatement:
    sid: str
    pid: str
    cid: str
    model_commitment: str
    benchmark_digest: str
    seed: str
    sampled_indices: dict[str, list[GlobalIndex]]


@dataclass(frozen=True)
class Passport:
    public_statement: PublicStatement
    proof: bytes | str
    expiry: int
    backend_id: str


@dataclass(frozen=True)
class PublicTranscript:
    sid: str
    policy: CertificationPolicy
    parties: list[str]
    seed_commitments: dict[str, str]
    seed_openings: dict[str, str]
    benchmark_digest: str
    holder_stratum_roots: dict[str, str] = field(default_factory=dict)
    holder_stratum_sizes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelOpening:
    arch_id: str
    qspec: QuantizationSpec
    parameters: dict[str, Any]
    randomness: str


@dataclass(frozen=True)
class MerklePathNode:
    sibling: str
    side: str


@dataclass(frozen=True)
class MembershipProof:
    local_root: str
    local_path: list[MerklePathNode]
    global_leaf: str
    global_path: list[MerklePathNode]
    holder_id: str
    stratum_id: str
    partition_size: int


@dataclass(frozen=True)
class WitnessRecord:
    record: BenchmarkRecord
    membership_proof: MembershipProof


@dataclass(frozen=True)
class MetricsResult:
    total: int
    correct: int
    violations: int
    per_stratum: dict[str, dict[str, int]]
    weighted_accuracy_num: int
    weighted_accuracy_den: int
    policy_passed: bool | None


@dataclass(frozen=True)
class Witness:
    model_opening: ModelOpening
    records: list[WitnessRecord]
    predictions: list[int]
    metrics: MetricsResult
    policy_id: str
    sid: str


@dataclass(frozen=True)
class Share:
    value: Any


@dataclass(frozen=True)
class WitnessShare:
    value: Any


@dataclass(frozen=True)
class MPCConfig:
    backend_id: str
    protocol: str = "mock"


@dataclass(frozen=True)
class MPCResult:
    ok: bool
    witness_shares: list[WitnessShare]
    preprocessing_seconds: float | None
    online_seconds: float | None
    communication_bytes: int | None
    peak_memory_bytes: int | None
    raw_logs: dict[str, Any]


@dataclass(frozen=True)
class RelationConfig:
    backend_id: str = "mock"
    proof_system: str = "groth16"
    curve: str = "BN254"
    protocol: str = "REP3"
    co_circom_path: str | None = None
    zkey_path: str | None = None
    verification_key_path: str | None = None
    network_config_paths: list[str] = field(default_factory=list)
    public_input_path: str | None = None
    work_dir: str | None = None


@dataclass(frozen=True)
class ProvingKey:
    backend_id: str
    key_id: str


@dataclass(frozen=True)
class VerificationKey:
    backend_id: str
    key_id: str


@dataclass(frozen=True)
class ProofKeys:
    proving_key: ProvingKey
    verification_key: VerificationKey


@dataclass(frozen=True)
class ProofResult:
    proof: bytes | str | None
    proof_seconds: float | None
    proof_size_bytes: int | None
    communication_bytes: int | None
    peak_memory_bytes: int | None
    success: bool
    backend_id: str
    raw_logs: dict[str, Any]


@dataclass(frozen=True)
class BenchmarkResult:
    run_id: str
    timestamp: str
    git_commit: str | None
    dataset: str
    model: str
    parameter_count: int
    sample_size: int
    holder_count: int
    committee_size: int
    network_mode: str
    mpc_backend: str
    proof_backend: str
    mpc_preprocessing_s: float | None
    mpc_online_s: float | None
    proof_s: float | None
    end_to_end_s: float | None
    communication_gb: float | None
    peak_memory_mb: float | None
    proof_size_bytes: int | None
    verify_ms: float | None
    plaintext_accuracy: float | None
    quantized_accuracy: float | None
    accuracy_delta: float | None
    policy_passed: bool | None
    proof_verified: bool | None
    status: str
    notes: str
