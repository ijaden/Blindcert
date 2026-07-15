from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Any

from blindcert.types import QuantizationSpec


class QuantizationError(ValueError):
    pass


def bounds(qspec: QuantizationSpec) -> tuple[int, int]:
    if qspec.signed:
        limit = 1 << (qspec.value_bits - 1)
        return -limit, limit - 1
    return 0, (1 << qspec.value_bits) - 1


def accumulator_bounds(qspec: QuantizationSpec) -> tuple[int, int]:
    limit = 1 << (qspec.accumulator_bits - 1)
    return -limit, limit - 1


def check_value_range(value: int, qspec: QuantizationSpec) -> None:
    lo, hi = bounds(qspec)
    if value < lo or value > hi:
        raise QuantizationError(f"value {value} outside quantized range [{lo}, {hi}]")


def check_accumulator_range(value: int, qspec: QuantizationSpec) -> None:
    lo, hi = accumulator_bounds(qspec)
    if value < lo or value > hi:
        raise QuantizationError(f"accumulator {value} outside range [{lo}, {hi}]")


def encode_scalar(value: float, qspec: QuantizationSpec) -> int:
    scaled = Decimal(str(value)) * (Decimal(2) ** qspec.scale_bits)
    if qspec.rounding == "nearest":
        rounded = int(scaled.to_integral_value(rounding=ROUND_HALF_EVEN))
    elif qspec.rounding == "half_up":
        rounded = int(scaled.to_integral_value(rounding=ROUND_HALF_UP))
    elif qspec.rounding == "floor":
        rounded = int(scaled // 1)
    else:
        raise QuantizationError(f"unsupported rounding mode: {qspec.rounding}")
    check_value_range(rounded, qspec)
    return rounded


def decode_scalar(value: int, qspec: QuantizationSpec) -> float:
    check_value_range(value, qspec)
    return value / float(1 << qspec.scale_bits)


def quantize_parameters(parameters: dict[str, Any], qspec: QuantizationSpec) -> dict[str, Any]:
    def convert(v: Any) -> Any:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            check_value_range(v, qspec)
            return v
        if isinstance(v, float):
            return encode_scalar(v, qspec)
        if isinstance(v, list):
            return [convert(x) for x in v]
        if isinstance(v, dict):
            return {str(k): convert(v[k]) for k in sorted(v)}
        raise QuantizationError(f"unsupported parameter type: {type(v).__name__}")

    return {str(k): convert(parameters[k]) for k in sorted(parameters)}


def flatten_parameters(parameters: dict[str, Any]) -> list[int]:
    out: list[int] = []

    def walk(v: Any) -> None:
        if isinstance(v, int):
            out.append(v)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k in sorted(v):
                walk(v[k])
        else:
            raise QuantizationError(f"non-integer quantized parameter: {v!r}")

    walk(parameters)
    return out
