from __future__ import annotations

from typing import Protocol

from blindcert.types import MPCConfig, MPCResult, PublicStatement, Share


class MPCBackend(Protocol):
    backend_id: str

    def setup(self, config: MPCConfig) -> None: ...

    def evaluate(
        self,
        public_statement: PublicStatement,
        model_shares: list[Share],
        benchmark_shares: list[Share],
    ) -> MPCResult: ...
