from __future__ import annotations

from pathlib import Path

from blindcert.datasets.tabular import load_csv_tabular
from blindcert.types import BenchmarkRecord


def load_security_csv(path: str | Path, holder_id: str, stratum_id: str = "security") -> list[BenchmarkRecord]:
    if not Path(path).exists():
        raise FileNotFoundError(f"security dataset not found: {path}")
    return load_csv_tabular(path, holder_id, stratum_id)
