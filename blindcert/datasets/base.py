from __future__ import annotations

from typing import Protocol

from blindcert.types import BenchmarkRecord


class DatasetAdapter(Protocol):
    name: str

    def load(self) -> list[BenchmarkRecord]: ...
