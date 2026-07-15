from __future__ import annotations

import secrets

from blindcert.sampling import derive_seed, seed_commitment, stratified_sample, verify_seed_openings
from blindcert.types import CertificationPolicy, PublicTranscript


def commit_and_reveal(
    sid: str,
    parties: list[str],
    fixed_openings: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str], str]:
    openings = {
        party: (fixed_openings or {}).get(party, secrets.token_hex(32)) for party in sorted(parties)
    }
    commitments = {party: seed_commitment(sid, party, openings[party]) for party in sorted(openings)}
    if not verify_seed_openings(sid, commitments, openings):
        raise RuntimeError("seed opening verification failed")
    return commitments, openings, derive_seed(sid, openings)


def build_transcript(
    sid: str,
    parties: list[str],
    policy: CertificationPolicy,
    benchmark_digest: str,
    holder_stratum_sizes: dict[tuple[str, str], int],
    fixed_openings: dict[str, str] | None = None,
) -> tuple[PublicTranscript, str]:
    commitments, openings, seed = commit_and_reveal(sid, parties, fixed_openings)
    transcript = PublicTranscript(
        sid=sid,
        policy=policy,
        parties=sorted(parties),
        seed_commitments=commitments,
        seed_openings=openings,
        benchmark_digest=benchmark_digest,
        holder_stratum_sizes={f"{h}:{g}": n for (h, g), n in sorted(holder_stratum_sizes.items())},
    )
    return transcript, seed


def sample_from_transcript(
    transcript: PublicTranscript,
    policy: CertificationPolicy,
    holder_stratum_sizes: dict[tuple[str, str], int],
):
    if not verify_seed_openings(transcript.sid, transcript.seed_commitments, transcript.seed_openings):
        raise ValueError("missing or invalid seed opening")
    seed = derive_seed(transcript.sid, transcript.seed_openings)
    return seed, stratified_sample(seed, policy, holder_stratum_sizes)
