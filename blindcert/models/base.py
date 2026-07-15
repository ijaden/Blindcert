from __future__ import annotations

from typing import Protocol

from blindcert.types import QuantizationSpec


class QuantizedModel(Protocol):
    arch_id: str
    qspec: QuantizationSpec
    parameters: dict[str, object]

    def predict_one(self, x: list[int] | list[list[int]]) -> int: ...

    def parameter_count(self) -> int: ...
