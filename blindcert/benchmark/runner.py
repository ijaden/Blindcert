from __future__ import annotations

from itertools import product


def benchmark_matrix() -> list[dict[str, object]]:
    models = ["logistic_regression", "mlp", "compact_cnn"]
    sample_sizes = [128, 512]
    holder_counts = [2, 3, 5]
    committee_sizes = [3, 5, 7]
    network_modes = ["lan", "wan"]
    proof_modes = ["mock", "single_prover", "collaborative"]
    return [
        {
            "model": model,
            "sample_size": sample_size,
            "holder_count": holder_count,
            "committee_size": committee_size,
            "network_mode": network_mode,
            "proof_backend": proof_backend,
        }
        for model, sample_size, holder_count, committee_size, network_mode, proof_backend in product(
            models, sample_sizes, holder_counts, committee_sizes, network_modes, proof_modes
        )
    ]
