from __future__ import annotations

from blindcert.policy import policy_id
from blindcert.proofs.mock_backend import MockProofBackend
from blindcert.proofs.single_prover_backend import SingleProverBackend
from blindcert.sampling import derive_seed, stratified_sample, verify_seed_openings
from blindcert.types import CertificationPolicy, Passport, PublicTranscript, VerificationKey


def _sizes_from_transcript(transcript: PublicTranscript) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for key, value in transcript.holder_stratum_sizes.items():
        holder_id, stratum_id = key.split(":", 1)
        out[(holder_id, stratum_id)] = int(value)
    return out


def _backend_for_id(backend_id: str):
    if backend_id == "mock":
        return MockProofBackend()
    if backend_id == "single_prover_dev":
        return SingleProverBackend()
    raise ValueError(f"unsupported verification backend: {backend_id}")


def verify_passport(
    transcript: PublicTranscript,
    policy: CertificationPolicy,
    verification_key: VerificationKey,
    passport: Passport,
    now: int,
) -> bool:
    """Verify a public passport without private model parameters or records."""
    if now > passport.expiry:
        return False
    if passport.backend_id != verification_key.backend_id:
        return False
    if transcript.policy != policy:
        return False
    if policy_id(policy) != passport.public_statement.pid:
        return False
    if transcript.sid != passport.public_statement.sid:
        return False
    if transcript.benchmark_digest != passport.public_statement.benchmark_digest:
        return False
    if passport.public_statement.cid != policy.cid:
        return False
    if not verify_seed_openings(transcript.sid, transcript.seed_commitments, transcript.seed_openings):
        return False
    seed = derive_seed(transcript.sid, transcript.seed_openings)
    if seed != passport.public_statement.seed:
        return False
    expected_samples = stratified_sample(seed, policy, _sizes_from_transcript(transcript))
    if expected_samples != passport.public_statement.sampled_indices:
        return False
    backend = _backend_for_id(passport.backend_id)
    return bool(backend.verify(verification_key, passport.public_statement, passport.proof))
