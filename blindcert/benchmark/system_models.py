from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegerModel:
    name: str
    kind: str
    layers: tuple[int, ...]
    parameters: tuple[int, ...]

    def predict(self, values: list[int]) -> int:
        if len(values) != self.layers[0] or any(v not in (-1, 0, 1) for v in values):
            raise ValueError('workload inputs must be ternary vectors of the configured dimension')
        if self.kind == 'polynomial_svm':
            score = self.parameters[0]
            offset = 1
            for value in values:
                score += self.parameters[offset] * value
                offset += 1
            for i, value in enumerate(values):
                for other in values[i:]:
                    score += self.parameters[offset] * value * other
                    offset += 1
            return int(score >= 0)
        offset = 0
        current = values
        for layer, (width, outputs) in enumerate(zip(self.layers, self.layers[1:])):
            result = []
            for _ in range(outputs):
                score = self.parameters[offset + width]
                score += sum(a * b for a, b in zip(current, self.parameters[offset:offset + width]))
                offset += width + 1
                result.append(score * score if layer < len(self.layers) - 2 else score)
            current = result
        return int(current[0] >= 0)

    def bounds(self) -> list[dict]:
        if self.kind == 'polynomial_svm':
            d = self.layers[0]
            bound = 1 + d + d * (d + 1) // 2
            return [{'absolute_bound': bound, 'signed_bits': bound.bit_length() + 1}]
        bound = 1
        result = []
        for layer, width in enumerate(self.layers[:-1]):
            linear_bound = width * bound + 1
            bound = linear_bound ** 2 if layer < len(self.layers) - 2 else linear_bound
            result.append({'preactivation_absolute_bound': linear_bound,
                           'absolute_bound': bound, 'signed_bits': bound.bit_length() + 1})
        return result


def generate_model(spec: dict, seed: int) -> IntegerModel:
    layers = tuple(spec['layers'])
    kind = spec['kind']
    if kind not in ('linear', 'quadratic_mlp', 'polynomial_svm'):
        raise ValueError(f'unsupported model kind: {kind}')
    if len(layers) < 2 or layers[-1] != 1 or any(v <= 0 for v in layers):
        raise ValueError('a positive-width binary classifier is required')
    d = layers[0]
    count = 1 + d + d * (d + 1) // 2 if kind == 'polynomial_svm' else sum(
        (a + 1) * b for a, b in zip(layers, layers[1:]))
    key = hashlib.sha256(f'{seed}:model:{spec["name"]}'.encode()).digest()
    rng = random.Random(int.from_bytes(key, 'big'))
    return IntegerModel(spec['name'], kind, layers, tuple(rng.choice((-1, 0, 1)) for _ in range(count)))
