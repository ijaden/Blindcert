from __future__ import annotations

from blindcert.commitment import commit_model
from blindcert.merkle import BenchmarkRegistry, register_benchmark
from blindcert.types import BenchmarkRecord, ModelOpening, QuantizationSpec


def register_model(
    arch_id: str, qspec: QuantizationSpec, parameters: dict[str, object], randomness: str | None = None
) -> tuple[str, ModelOpening]:
    return commit_model(arch_id, qspec, parameters, randomness)


def register_dataset(records: list[BenchmarkRecord]) -> BenchmarkRegistry:
    return register_benchmark(records)
