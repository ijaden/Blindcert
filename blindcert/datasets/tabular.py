from __future__ import annotations

import csv
from pathlib import Path

from blindcert.hashing import hash_obj
from blindcert.types import BenchmarkRecord


def synthetic_binary_tabular(
    holder_count: int = 2,
    strata: tuple[str, ...] = ("g0", "g1"),
    per_holder_stratum: int = 16,
) -> list[BenchmarkRecord]:
    records: list[BenchmarkRecord] = []
    for holder in range(holder_count):
        for stratum_pos, stratum_id in enumerate(strata):
            for i in range(per_holder_stratum):
                x0 = (i + holder + stratum_pos) % 4 - 1
                x1 = (2 * i + holder) % 5 - 2
                y = 1 if x0 + x1 >= 0 else 0
                nonce = bytes.fromhex(
                    hash_obj(
                        "synthetic_record_nonce_v1",
                        {"holder": holder, "stratum": stratum_id, "local_index": i},
                    )[:32]
                )
                records.append(
                    BenchmarkRecord(
                        holder_id=f"h{holder}",
                        stratum_id=stratum_id,
                        local_index=i,
                        x=[x0, x1],
                        y=y,
                        attribute=stratum_pos,
                        nonce=nonce,
                    )
                )
    return records


def load_csv_tabular(path: str | Path, holder_id: str, stratum_id: str) -> list[BenchmarkRecord]:
    out: list[BenchmarkRecord] = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            x = [int(v) for k, v in sorted(row.items()) if k.startswith("x")]
            y = int(row["y"])
            attribute = int(row["attribute"]) if row.get("attribute") not in (None, "") else None
            nonce = (
                bytes.fromhex(row["nonce"])
                if row.get("nonce")
                else bytes.fromhex(hash_obj("csv_record_nonce_v1", {"path": str(path), "i": i})[:32])
            )
            out.append(BenchmarkRecord(holder_id, stratum_id, i, x, y, attribute, nonce))
    return out
