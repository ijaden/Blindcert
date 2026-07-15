from __future__ import annotations

from blindcert.models.base import QuantizedModel
from blindcert.plaintext.metrics import compute_metrics
from blindcert.types import BenchmarkRecord, CertificationPolicy, MetricsResult


def predict(model: QuantizedModel, records: list[BenchmarkRecord]) -> list[int]:
    return [model.predict_one(record.x) for record in records]


def evaluate(
    model: QuantizedModel,
    records: list[BenchmarkRecord],
    policy: CertificationPolicy | None = None,
) -> tuple[list[int], MetricsResult]:
    predictions = predict(model, records)
    return predictions, compute_metrics(records, predictions, policy)
