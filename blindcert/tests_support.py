from __future__ import annotations

import time
from dataclasses import replace

from blindcert.protocol.verify import verify_passport
from blindcert.session import run_demo_end_to_end


def run_adversarial_checks() -> dict[str, bool]:
    result = run_demo_end_to_end()
    passport = result.passport
    transcript = result.transcript
    policy = transcript.policy
    vk = result.verification_key
    now = int(time.time())
    tampered_statement = replace(passport.public_statement, seed="00")
    tampered_passport = replace(passport, public_statement=tampered_statement)
    expired = replace(passport, expiry=now - 1)
    wrong_backend = replace(passport, backend_id="collaborative")
    wrong_proof = replace(passport, proof="00")
    return {
        "honest_accepts": verify_passport(transcript, policy, vk, passport, now),
        "modified_statement_rejected": not verify_passport(transcript, policy, vk, tampered_passport, now),
        "expired_rejected": not verify_passport(transcript, policy, vk, expired, now),
        "backend_replacement_rejected": not verify_passport(transcript, policy, vk, wrong_backend, now),
        "proof_modification_rejected": not verify_passport(transcript, policy, vk, wrong_proof, now),
    }
