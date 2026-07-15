from blindcert.session import run_demo_end_to_end


def test_honest_run_creates_verifiable_passport() -> None:
    result = run_demo_end_to_end()
    assert result.verified
