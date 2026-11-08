from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


SCALAR_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
MONTGOMERY_INVERSE = pow(1 << 256, -1, SCALAR_FIELD)


def u64(value: int) -> bytes:
    return struct.pack('<Q', value)


def field(value: int) -> bytes:
    if not 0 <= value < SCALAR_FIELD:
        raise ValueError('noncanonical BN254 scalar')
    return value.to_bytes(32, 'little')


def read_authenticated_share_values(path: Path, count: int) -> list[int]:
    data = path.read_bytes()
    if len(data) < 8:
        raise ValueError('truncated persistence header')
    header_size = struct.unpack_from('<Q', data)[0]
    offset = 8 + header_size
    if offset > len(data) or len(data) - offset != count * 64:
        raise ValueError('unexpected persistence size for BN254 authenticated shares')
    header = data[8:offset]
    expected = b'SPDZ gfp' + bytes([0]) + struct.pack('<I', 32) + SCALAR_FIELD.to_bytes(32, 'big') + struct.pack('<I', 1)
    if len(header) != len(expected) + 32 or header[:len(expected)] != expected:
        raise ValueError('persistence header does not identify the BN254 scalar field')
    values = []
    for index in range(count):
        raw = int.from_bytes(data[offset + index * 64:offset + index * 64 + 32], 'little')
        if raw >= SCALAR_FIELD:
            raise ValueError('noncanonical Montgomery share')
        values.append(raw * MONTGOMERY_INVERSE % SCALAR_FIELD)
    return values


def ark_map(values: dict[str, list[bytes]]) -> bytes:
    encoded = u64(len(values))
    for key, items in sorted(values.items()):
        name = key.encode('utf-8')
        encoded += u64(len(name)) + name + u64(len(items)) + b''.join(items)
    return u64(len(encoded)) + encoded


def encode_rep3_input(own: list[int], previous: list[int], layout: dict[str, int],
                      public: dict[str, list[int]]) -> bytes:
    if len(own) != len(previous) or len(own) != sum(layout.values()):
        raise ValueError('share count does not match circuit input layout')
    if set(public) & set(layout):
        raise ValueError('public and secret input names overlap')
    shared = {}
    offset = 0
    for name, size in layout.items():
        if size < 1:
            raise ValueError('input sizes must be positive')
        shared[name] = [field(own[i]) + field(previous[i]) for i in range(offset, offset + size)]
        offset += size
    return (ark_map({key: [field(v) for v in values] for key, values in public.items()})
            + ark_map(shared) + u64(0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert one party's checked MASCOT shares to REP3 input.")
    parser.add_argument('--own', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--layout', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--public', type=Path)
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text())
    count = sum(layout.values())
    own = read_authenticated_share_values(args.own, count)
    previous = read_authenticated_share_values(args.previous, count)
    args.out.write_bytes(encode_rep3_input(own, previous, layout, json.loads(args.public.read_text()) if args.public else {}))
    args.out.chmod(0o600)


if __name__ == '__main__':
    main()
