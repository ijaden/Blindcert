from __future__ import annotations

from pathlib import Path

from blindcert.types import BenchmarkRecord


def load_mnist_like_npz(path: str | Path, holder_id: str, stratum_id: str) -> list[BenchmarkRecord]:
    raise RuntimeError(
        "MNIST/Fashion-MNIST adapter requires a local loader integration. "
        f"Provide a local path and extend this adapter: {path}"
    )
