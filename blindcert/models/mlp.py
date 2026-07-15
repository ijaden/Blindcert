from __future__ import annotations

from dataclasses import dataclass

from blindcert.quantization import check_accumulator_range, flatten_parameters
from blindcert.types import QuantizationSpec


def relu(x: int) -> int:
    return max(0, x)


@dataclass(frozen=True)
class MLPModel:
    qspec: QuantizationSpec
    parameters: dict[str, object]
    arch_id: str = "mlp"

    def predict_one(self, x: list[int] | list[list[int]]) -> int:
        if not x or isinstance(x[0], list):
            raise ValueError("MLP expects a flat vector")
        w1 = self.parameters["w1"]
        b1 = self.parameters["b1"]
        w2 = self.parameters["w2"]
        b2_obj = self.parameters.get("b2", 0)
        if not isinstance(b2_obj, int):
            raise ValueError("b2 must be an integer")
        b2 = b2_obj
        if not isinstance(w1, list) or not isinstance(b1, list) or not isinstance(w2, list):
            raise ValueError("invalid MLP parameters")
        hidden: list[int] = []
        for row, bias in zip(w1, b1, strict=True):
            acc = int(bias)
            for wi, xi in zip(row, x, strict=True):
                acc += int(wi) * int(xi)
                check_accumulator_range(acc, self.qspec)
            hidden.append(relu(acc))
        out = b2
        for wi, hi in zip(w2, hidden, strict=True):
            out += int(wi) * hi
            check_accumulator_range(out, self.qspec)
        return 1 if out >= 0 else 0

    def parameter_count(self) -> int:
        return len(flatten_parameters(self.parameters))
