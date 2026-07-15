from __future__ import annotations

import hashlib
from typing import Any

from blindcert.serialization import canonical_bytes


def hash_bytes(domain: str, payload: bytes) -> str:
    h = hashlib.sha256()
    h.update(b"BlindCert:")
    h.update(domain.encode("utf-8"))
    h.update(b":")
    h.update(payload)
    return h.hexdigest()


def hash_obj(domain: str, obj: Any) -> str:
    return hash_bytes(domain, canonical_bytes(obj))
