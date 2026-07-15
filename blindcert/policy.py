from __future__ import annotations

import math

from blindcert.hashing import hash_obj
from blindcert.types import CertificationPolicy, MetricsResult


def policy_id(policy: CertificationPolicy) -> str:
    return hash_obj("certification_policy_v1", policy)


def ratio_at_least(num: int, den: int, threshold_num: int, threshold_den: int) -> bool:
    if den <= 0 or threshold_den <= 0:
        raise ValueError("denominators must be positive")
    return num * threshold_den >= threshold_num * den


def evaluate_policy(policy: CertificationPolicy, metrics: MetricsResult) -> bool:
    if not ratio_at_least(
        metrics.weighted_accuracy_num,
        metrics.weighted_accuracy_den,
        policy.tau_all_num,
        policy.tau_all_den,
    ):
        return False
    if not ratio_at_least(policy.beta_num - metrics.violations, policy.beta_den, 0, 1):
        return False
    for stratum_id, sp in policy.strata.items():
        counters = metrics.per_stratum.get(stratum_id)
        if counters is None:
            return False
        if not ratio_at_least(counters["correct"], counters["total"], sp.tau_num, sp.tau_den):
            return False
    return True


def statistical_delta(population_size: int, sample_size: int, epsilon: float) -> float:
    if population_size <= 0 or sample_size <= 0 or sample_size > population_size:
        raise ValueError("invalid population/sample sizes")
    denom = 1 - ((sample_size - 1) / population_size)
    return math.exp((-2 * sample_size * epsilon * epsilon) / denom)


def statistical_report(policy: CertificationPolicy) -> dict[str, float]:
    deltas = {
        g: statistical_delta(sp.population_size, sp.sample_size, sp.epsilon)
        for g, sp in policy.strata.items()
    }
    deltas["all"] = sum(deltas.values())
    return deltas
