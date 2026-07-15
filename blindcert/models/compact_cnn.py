from __future__ import annotations

from dataclasses import dataclass

from blindcert.quantization import check_accumulator_range, flatten_parameters
from blindcert.types import QuantizationSpec


@dataclass(frozen=True)
class CompactCNNModel:
    """Small integer CNN for tests: one valid 2D convolution, ReLU, linear head."""

    qspec: QuantizationSpec
    parameters: dict[str, object]
    arch_id: str = "compact_cnn"

    def predict_one(self, x: list[int] | list[list[int]]) -> int:
        if not x or not isinstance(x[0], list):
            raise ValueError("compact CNN expects a 2D integer image")
        kernel = self.parameters["kernel"]
        conv_bias_obj = self.parameters.get("conv_bias", 0)
        if not isinstance(conv_bias_obj, int):
            raise ValueError("conv_bias must be an integer")
        conv_bias = conv_bias_obj
        head = self.parameters["head"]
        head_bias_obj = self.parameters.get("head_bias", 0)
        if not isinstance(head_bias_obj, int):
            raise ValueError("head_bias must be an integer")
        head_bias = head_bias_obj
        if not isinstance(kernel, list) or not isinstance(head, list):
            raise ValueError("invalid CNN parameters")
        kh = len(kernel)
        kw = len(kernel[0])
        features: list[int] = []
        for r in range(len(x) - kh + 1):
            for c in range(len(x[0]) - kw + 1):
                acc = conv_bias
                for kr in range(kh):
                    for kc in range(kw):
                        acc += int(kernel[kr][kc]) * int(x[r + kr][c + kc])
                        check_accumulator_range(acc, self.qspec)
                features.append(max(0, acc))
        if len(head) != len(features):
            raise ValueError("CNN head dimension mismatch")
        out = head_bias
        for wi, fi in zip(head, features, strict=True):
            out += int(wi) * fi
            check_accumulator_range(out, self.qspec)
        return 1 if out >= 0 else 0

    def parameter_count(self) -> int:
        return len(flatten_parameters(self.parameters))
