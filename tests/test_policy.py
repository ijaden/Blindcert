from blindcert.plaintext.metrics import compute_metrics
from blindcert.session import demo_policy
from blindcert.types import BenchmarkRecord


def test_policy_uses_integer_thresholds() -> None:
    policy = demo_policy()
    records = [
        BenchmarkRecord("h0", "g0", 0, [0, 0], 1, 0, b"0"),
        BenchmarkRecord("h0", "g0", 1, [0, 0], 1, 0, b"1"),
        BenchmarkRecord("h0", "g0", 2, [0, 0], 1, 0, b"2"),
        BenchmarkRecord("h0", "g0", 3, [0, 0], 1, 0, b"3"),
    ]
    policy.strata["g0"].sample_size
    metrics = compute_metrics(records, [1, 1, 1, 0])
    assert metrics.correct == 3
