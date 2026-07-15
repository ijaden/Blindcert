from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from blindcert.policy import evaluate_policy
from blindcert.types import BenchmarkRecord, CertificationPolicy, MetricsResult


def default_safety_predicate(prediction: int, attribute: int | None) -> bool:
    return not (attribute == 1 and prediction == 1)


def compute_metrics(
    records: list[BenchmarkRecord],
    predictions: list[int],
    policy: CertificationPolicy | None = None,
    safety_predicate: Callable[[int, int | None], bool] = default_safety_predicate,
) -> MetricsResult:
    if len(records) != len(predictions):
        raise ValueError("records/predictions length mismatch")
    per: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "correct": 0, "violations": 0}
    )
    correct = 0
    violations = 0
    for rec, pred in zip(records, predictions, strict=True):
        ok = int(pred) == int(rec.y)
        safe = safety_predicate(int(pred), rec.attribute)
        per[rec.stratum_id]["total"] += 1
        per[rec.stratum_id]["correct"] += int(ok)
        per[rec.stratum_id]["violations"] += int(not safe)
        correct += int(ok)
        violations += int(not safe)

    metrics = MetricsResult(
        total=len(records),
        correct=correct,
        violations=violations,
        per_stratum={k: dict(v) for k, v in sorted(per.items())},
        weighted_accuracy_num=correct,
        weighted_accuracy_den=max(len(records), 1),
        policy_passed=None,
    )
    if policy is None:
        return metrics
    return MetricsResult(
        **{**metrics.__dict__, "policy_passed": evaluate_policy(policy, metrics)}
    )
