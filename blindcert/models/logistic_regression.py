from __future__ import annotations

from dataclasses import dataclass

from blindcert.quantization import check_accumulator_range, flatten_parameters
from blindcert.types import QuantizationSpec


@dataclass(frozen=True)
class LogisticRegressionModel:
    qspec: QuantizationSpec
    parameters: dict[str, object]
    arch_id: str = "logistic_regression"

    def predict_one(self, x: list[int] | list[list[int]]) -> int:
        if not x or isinstance(x[0], list):
            raise ValueError("logistic regression expects a flat vector")
        weights = self.parameters["weights"]
        bias_obj = self.parameters.get("bias", 0)
        if not isinstance(bias_obj, int):
            raise ValueError("bias must be an integer")
        bias = bias_obj
        if not isinstance(weights, list):
            raise ValueError("weights must be a list")
        if len(weights) != len(x):
            raise ValueError("input dimension mismatch")
        acc = bias
        for wi, xi in zip(weights, x, strict=True):
            acc += int(wi) * int(xi)
            check_accumulator_range(acc, self.qspec)
        return 1 if acc >= 0 else 0

    def parameter_count(self) -> int:
        return len(flatten_parameters(self.parameters))
