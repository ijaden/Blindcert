from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def to_canonical(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return {"__bytes__": obj.hex()}
    if is_dataclass(obj) and not isinstance(obj, type):
        return to_canonical(asdict(obj))
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, tuple):
        return [to_canonical(v) for v in obj]
    if isinstance(obj, list):
        return [to_canonical(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): to_canonical(obj[k]) for k in sorted(obj)}
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(to_canonical(obj), sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def write_json(path: str | Path, obj: Any) -> None:
    Path(path).write_text(json.dumps(to_canonical(obj), indent=2, sort_keys=True) + "\n", encoding="utf-8")
