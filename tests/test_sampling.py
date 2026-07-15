from blindcert.sampling import sample_without_replacement, seed_commitment, verify_seed_openings


def test_sampling_is_deterministic_without_replacement() -> None:
    a = sample_without_replacement("seed", "g0", 20, 8)
    b = sample_without_replacement("seed", "g0", 20, 8)
    assert a == b
    assert len(a) == len(set(a)) == 8


def test_invalid_seed_opening_rejected() -> None:
    commitments = {"p0": seed_commitment("sid", "p0", "aa")}
    assert verify_seed_openings("sid", commitments, {"p0": "aa"})
    assert not verify_seed_openings("sid", commitments, {"p0": "bb"})
