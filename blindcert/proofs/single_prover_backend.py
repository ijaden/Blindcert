from __future__ import annotations

from blindcert.proofs.mock_backend import MockProofBackend


class SingleProverBackend(MockProofBackend):
    backend_id = "single_prover_dev"
