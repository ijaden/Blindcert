from __future__ import annotations

from collections import defaultdict

from blindcert.hashing import hash_obj
from blindcert.types import CertificationPolicy, GlobalIndex, PublicTranscript


def seed_commitment(sid: str, party_id: str, seed_hex: str) -> str:
    return hash_obj("seed_commitment_v1", {"sid": sid, "party_id": party_id, "seed": seed_hex})


def derive_seed(sid: str, openings: dict[str, str]) -> str:
    if not openings:
        raise ValueError("missing seed openings")
    return hash_obj(
        "joint_seed_v1",
        {"sid": sid, "openings": {party: openings[party] for party in sorted(openings)}},
    )


def verify_seed_openings(
    sid: str, seed_commitments: dict[str, str], seed_openings: dict[str, str]
) -> bool:
    if set(seed_commitments) != set(seed_openings):
        return False
    return all(seed_commitment(sid, p, seed_openings[p]) == seed_commitments[p] for p in seed_commitments)


def sample_without_replacement(seed: str, stratum_id: str, population_size: int, sample_size: int) -> list[int]:
    if sample_size < 0 or population_size < 0 or sample_size > population_size:
        raise ValueError("invalid sample size")
    selected: set[int] = set()
    counter = 0
    while len(selected) < sample_size:
        digest = hash_obj("sample_draw_v1", {"seed": seed, "stratum_id": stratum_id, "counter": counter})
        candidate = int(digest, 16) % population_size
        selected.add(candidate)
        counter += 1
    return list(selected)


def group_indices(indices: list[GlobalIndex]) -> dict[str, list[GlobalIndex]]:
    grouped: dict[str, list[GlobalIndex]] = defaultdict(list)
    for idx in indices:
        grouped[idx.stratum_id].append(idx)
    return {g: sorted(v, key=lambda x: (x.holder_id, x.local_index)) for g, v in sorted(grouped.items())}


def build_population_indices(partition_sizes: dict[tuple[str, str], int]) -> dict[str, list[GlobalIndex]]:
    out: dict[str, list[GlobalIndex]] = defaultdict(list)
    for holder_id, stratum_id in sorted(partition_sizes):
        for local_index in range(partition_sizes[(holder_id, stratum_id)]):
            out[stratum_id].append(GlobalIndex(holder_id, stratum_id, local_index))
    return {g: v for g, v in sorted(out.items())}


def stratified_sample(
    seed: str,
    policy: CertificationPolicy,
    partition_sizes: dict[tuple[str, str], int],
) -> dict[str, list[GlobalIndex]]:
    population = build_population_indices(partition_sizes)
    sampled: dict[str, list[GlobalIndex]] = {}
    for stratum_id, stratum_policy in sorted(policy.strata.items()):
        if stratum_id not in population:
            raise ValueError(f"stratum {stratum_id} not in registered benchmark")
        if len(population[stratum_id]) != stratum_policy.population_size:
            raise ValueError(f"population size mismatch for stratum {stratum_id}")
        draws = sample_without_replacement(
            seed, stratum_id, stratum_policy.population_size, stratum_policy.sample_size
        )
        sampled[stratum_id] = [population[stratum_id][i] for i in draws]
    return sampled


def reconstruct_seed_and_samples(
    transcript: PublicTranscript,
    policy: CertificationPolicy,
    partition_sizes: dict[tuple[str, str], int],
) -> tuple[str, dict[str, list[GlobalIndex]]]:
    if transcript.policy != policy:
        raise ValueError("policy mismatch in transcript")
    if not verify_seed_openings(transcript.sid, transcript.seed_commitments, transcript.seed_openings):
        raise ValueError("invalid seed opening")
    seed = derive_seed(transcript.sid, transcript.seed_openings)
    return seed, stratified_sample(seed, policy, partition_sizes)
