from blindcert.proofs.collaborative_backend import CollaborativeProofBackend
from blindcert.types import RelationConfig


def test_co_circom_binary_is_detected_when_installed() -> None:
    backend = CollaborativeProofBackend()
    keys = backend.setup(RelationConfig(backend_id="collaborative"))
    assert keys.proving_key.backend_id == "collaborative"
    assert keys.verification_key.backend_id == "collaborative"
