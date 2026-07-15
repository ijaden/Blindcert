from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from blindcert.hashing import hash_obj
from blindcert.types import BenchmarkRecord, MembershipProof, MerklePathNode


def record_leaf(record: BenchmarkRecord) -> str:
    return hash_obj(
        "benchmark_record_leaf_v1",
        {
            "holder_id": record.holder_id,
            "stratum_id": record.stratum_id,
            "local_index": record.local_index,
            "nonce": record.nonce,
            "x": record.x,
            "y": record.y,
            "attribute": record.attribute,
        },
    )


def parent_hash(left: str, right: str) -> str:
    return hash_obj("merkle_parent_v1", {"left": left, "right": right})


class MerkleTree:
    def __init__(self, leaves: Iterable[str]) -> None:
        self.leaves = list(leaves)
        if not self.leaves:
            raise ValueError("MerkleTree requires at least one leaf")
        self.levels: list[list[str]] = [self.leaves]
        level = self.leaves
        while len(level) > 1:
            nxt: list[str] = []
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if i + 1 < len(level) else left
                nxt.append(parent_hash(left, right))
            self.levels.append(nxt)
            level = nxt

    @property
    def root(self) -> str:
        return self.levels[-1][0]

    def proof(self, index: int) -> list[MerklePathNode]:
        if index < 0 or index >= len(self.leaves):
            raise IndexError("leaf index out of range")
        path: list[MerklePathNode] = []
        idx = index
        for level in self.levels[:-1]:
            sibling_idx = idx ^ 1
            if sibling_idx >= len(level):
                sibling_idx = idx
            side = "left" if sibling_idx < idx else "right"
            path.append(MerklePathNode(sibling=level[sibling_idx], side=side))
            idx //= 2
        return path


def verify_merkle_path(leaf: str, path: list[MerklePathNode], root: str) -> bool:
    cur = leaf
    for node in path:
        if node.side == "left":
            cur = parent_hash(node.sibling, cur)
        elif node.side == "right":
            cur = parent_hash(cur, node.sibling)
        else:
            return False
    return cur == root


def global_leaf(holder_id: str, stratum_id: str, size: int, local_root: str) -> str:
    return hash_obj(
        "benchmark_global_leaf_v1",
        {"holder_id": holder_id, "stratum_id": stratum_id, "N": size, "root": local_root},
    )


@dataclass
class BenchmarkRegistry:
    digest: str
    local_trees: dict[tuple[str, str], MerkleTree]
    global_tree: MerkleTree
    global_leaves: dict[tuple[str, str], str]
    global_positions: dict[tuple[str, str], int]
    partition_sizes: dict[tuple[str, str], int]
    records: dict[tuple[str, str, int], BenchmarkRecord]

    def membership_proof(self, record: BenchmarkRecord) -> MembershipProof:
        key = (record.holder_id, record.stratum_id)
        rec_key = (record.holder_id, record.stratum_id, record.local_index)
        if rec_key not in self.records or self.records[rec_key] != record:
            raise ValueError("record is not registered at the claimed index")
        local_tree = self.local_trees[key]
        return MembershipProof(
            local_root=local_tree.root,
            local_path=local_tree.proof(record.local_index),
            global_leaf=self.global_leaves[key],
            global_path=self.global_tree.proof(self.global_positions[key]),
            holder_id=record.holder_id,
            stratum_id=record.stratum_id,
            partition_size=self.partition_sizes[key],
        )


def register_benchmark(records: list[BenchmarkRecord]) -> BenchmarkRegistry:
    if not records:
        raise ValueError("cannot register empty benchmark")
    grouped: dict[tuple[str, str], list[BenchmarkRecord]] = {}
    seen: set[tuple[str, str, int]] = set()
    record_map: dict[tuple[str, str, int], BenchmarkRecord] = {}
    for rec in records:
        key3 = (rec.holder_id, rec.stratum_id, rec.local_index)
        if key3 in seen:
            raise ValueError(f"duplicate record index: {key3}")
        seen.add(key3)
        record_map[key3] = rec
        grouped.setdefault((rec.holder_id, rec.stratum_id), []).append(rec)

    local_trees: dict[tuple[str, str], MerkleTree] = {}
    global_items: list[tuple[tuple[str, str], str]] = []
    sizes: dict[tuple[str, str], int] = {}
    for key in sorted(grouped):
        ordered = sorted(grouped[key], key=lambda r: r.local_index)
        expected = list(range(len(ordered)))
        actual = [r.local_index for r in ordered]
        if actual != expected:
            raise ValueError(f"partition {key} local indices must be contiguous from zero")
        leaves = [record_leaf(r) for r in ordered]
        tree = MerkleTree(leaves)
        local_trees[key] = tree
        sizes[key] = len(ordered)
        global_items.append((key, global_leaf(key[0], key[1], len(ordered), tree.root)))

    global_leaves = {key: leaf for key, leaf in global_items}
    global_positions = {key: pos for pos, (key, _leaf) in enumerate(global_items)}
    global_tree = MerkleTree([leaf for _key, leaf in global_items])
    return BenchmarkRegistry(
        digest=global_tree.root,
        local_trees=local_trees,
        global_tree=global_tree,
        global_leaves=global_leaves,
        global_positions=global_positions,
        partition_sizes=sizes,
        records=record_map,
    )


def verify_record_membership(record: BenchmarkRecord, proof: MembershipProof, benchmark_digest: str) -> bool:
    if proof.holder_id != record.holder_id or proof.stratum_id != record.stratum_id:
        return False
    if record.local_index < 0 or record.local_index >= proof.partition_size:
        return False
    leaf = record_leaf(record)
    if not verify_merkle_path(leaf, proof.local_path, proof.local_root):
        return False
    expected_global_leaf = global_leaf(
        record.holder_id, record.stratum_id, proof.partition_size, proof.local_root
    )
    if expected_global_leaf != proof.global_leaf:
        return False
    return verify_merkle_path(proof.global_leaf, proof.global_path, benchmark_digest)
