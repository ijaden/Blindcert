from blindcert.tests_support import run_adversarial_checks


def test_adversarial_public_verification_cases() -> None:
    checks = run_adversarial_checks()
    assert all(checks.values())
