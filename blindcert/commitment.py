from __future__ import annotations

import secrets

from blindcert.hashing import hash_obj
from blindcert.quantization import flatten_parameters
from blindcert.types import ModelOpening, QuantizationSpec


def commit_model(
    arch_id: str,
    qspec: QuantizationSpec,
    parameters: dict[str, object],
    randomness: str | None = None,
) -> tuple[str, ModelOpening]:
    r = randomness or secrets.token_hex(32)
    opening = ModelOpening(arch_id=arch_id, qspec=qspec, parameters=parameters, randomness=r)
    payload = {
        "arch_id": arch_id,
        "qspec": qspec,
        "ordered_quantized_parameters": flatten_parameters(parameters),
        "parameters": parameters,
        "randomness": r,
    }
    return hash_obj("model_commitment_v1", payload), opening


def verify_model_commitment(commitment: str, opening: ModelOpening) -> bool:
    expected, _ = commit_model(
        opening.arch_id,
        opening.qspec,
        opening.parameters,
        randomness=opening.randomness,
    )
    return expected == commitment
