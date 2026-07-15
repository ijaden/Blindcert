from __future__ import annotations

from blindcert.models.compact_cnn import CompactCNNModel
from blindcert.models.logistic_regression import LogisticRegressionModel
from blindcert.models.mlp import MLPModel
from blindcert.types import ModelOpening


def model_from_opening(opening: ModelOpening):
    if opening.arch_id == "logistic_regression":
        return LogisticRegressionModel(opening.qspec, opening.parameters)
    if opening.arch_id == "mlp":
        return MLPModel(opening.qspec, opening.parameters)
    if opening.arch_id == "compact_cnn":
        return CompactCNNModel(opening.qspec, opening.parameters)
    raise ValueError(f"unknown architecture: {opening.arch_id}")
