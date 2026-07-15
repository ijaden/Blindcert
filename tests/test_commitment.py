from dataclasses import replace

from blindcert.commitment import commit_model, verify_model_commitment
from blindcert.types import QuantizationSpec


def test_model_commitment_binds_parameters() -> None:
    qspec = QuantizationSpec(0, 8, 32)
    commitment, opening = commit_model("logistic_regression", qspec, {"weights": [1, 2], "bias": 0}, "aa")
    assert verify_model_commitment(commitment, opening)
    tampered = replace(opening, parameters={"weights": [1, 3], "bias": 0})
    assert not verify_model_commitment(commitment, tampered)
