from blindcert.serialization import canonical_json
from blindcert.session import run_demo_end_to_end


def test_repeated_runs_reproduce_public_statement() -> None:
    a = run_demo_end_to_end()
    b = run_demo_end_to_end()
    assert canonical_json(a.passport.public_statement) == canonical_json(b.passport.public_statement)
