from __future__ import annotations

import ast
import functools
import math
import re
from pathlib import Path

from blindcert.benchmark.system_models import generate_model
from blindcert.bridge.mpspdz_rep3 import SCALAR_FIELD as Q


ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'external/co-snarks-src/co-circom/co-circom/examples/lib'


@functools.lru_cache(maxsize=32)
def constants(name: str, width: int):
    text = (LIB / 'poseidon_constants.circom').read_text()
    text = text.split(f'function POSEIDON_{name}(t)', 1)[1]
    text = re.split(r'if\s*\(t\s*==\s*' + str(width) + r'\)', text, maxsplit=1)[1]
    start = text.index('[')
    depth = 0
    for end in range(start, len(text)):
        depth += (text[end] == '[') - (text[end] == ']')
        if depth == 0:
            return ast.literal_eval(text[start:end + 1])
    raise ValueError('invalid Poseidon constant array')


def poseidon(values: list[int]) -> int:
    t = len(values) + 1
    rounds = [56, 57, 56, 60, 60, 63, 64, 63, 60, 66, 60, 65, 70, 60, 64, 68][t - 2]
    c, s, m, p = [constants(name, t) for name in ('C', 'S', 'M', 'P')]
    def mix(state, matrix):
        return [sum(state[j] * matrix[j][i] for j in range(t)) % Q for i in range(t)]
    state = [(a + b) % Q for a, b in zip([0, *values], c[:t])]
    for r in range(3):
        state = mix([(pow(v, 5, Q) + c[(r + 1) * t + j]) % Q for j, v in enumerate(state)], m)
    state = mix([(pow(v, 5, Q) + c[4 * t + j]) % Q for j, v in enumerate(state)], p)
    for r in range(rounds):
        state[0] = (pow(state[0], 5, Q) + c[5 * t + r]) % Q
        first = sum(state[j] * s[(2 * t - 1) * r + j] for j in range(t)) % Q
        state = [first, *[(state[j] + state[0] * s[(2 * t - 1) * r + t + j - 1]) % Q for j in range(1, t)]]
    for r in range(3):
        state = mix([(pow(v, 5, Q) + c[5 * t + rounds + r * t + j]) % Q for j, v in enumerate(state)], m)
    return sum(pow(state[j], 5, Q) * m[j][0] for j in range(t)) % Q


def digest(domain: int, values: list[int]) -> int:
    state = domain * 1000000000 + len(values)
    for offset in range(0, len(values), 15):
        chunk = values[offset:offset + 15]
        state = poseidon([state, *chunk, *([0] * (15 - len(chunk)))])
    return state


def leaf(holder: int, record: dict) -> int:
    return digest(2, [holder, record['stratum'], record['local_index'], int(record['nonce']),
                      *record['x'], record['y'], record['attribute']])


def tree(leaves: list[int]) -> list[list[int]]:
    if len(leaves) < 2 or len(leaves) & (len(leaves) - 1):
        raise ValueError('partition size must be a power of two and at least two')
    levels = [leaves]
    while len(levels[-1]) > 1:
        previous = levels[-1]
        levels.append([poseidon(previous[i:i + 2]) for i in range(0, len(previous), 2)])
    return levels


def policy(config: dict) -> dict:
    n = config['sample_size'] // 2
    delta = config.get('statistical_failure_probability', .05)
    tau = config.get('minimum_accuracy', .75)
    beta = config.get('maximum_violation_rate', .25)
    epsilon = math.sqrt(math.log(4 / delta) / (2 * n))
    required = math.ceil((tau + epsilon) * n)
    allowed = math.floor((beta - epsilon) * n)
    if not 0 <= tau <= 1 or not 0 < delta < 1 or required > n or allowed < 0:
        raise ValueError('infeasible statistical policy for the fixed sample size')
    return {'minimum_accuracy': tau, 'maximum_violation_rate': beta, 'delta': delta,
            'epsilon': epsilon, 'required_correct_per_stratum': required,
            'allowed_violations_per_stratum': allowed, 'population_weights': [0.5, 0.5]}


def arithmetic(spec: dict, sample: int, language: str) -> tuple[list[str], list[str]]:
    lines, scores = [], []
    counter = 0
    def mul(a, b):
        nonlocal counter
        name = f'v{counter}'
        counter += 1
        lines.append(f'signal {name}; {name} <== ({a}) * ({b});' if language == 'circom' else f'{name} = ({a}) * ({b})')
        return name
    def linear(parts):
        nonlocal counter
        name = f'v{counter}'
        counter += 1
        expression = ' + '.join(parts)
        lines.append(f'signal {name}; {name} <== {expression};' if language == 'circom' else f'{name} = {expression}')
        return name
    d = spec['layers'][0]
    for row in range(sample):
        x = [f'x[{row * d + j}]' for j in range(d)]
        if spec['kind'] == 'polynomial_svm':
            terms = ['theta[0]'] + [mul(f'theta[{j + 1}]', v) for j, v in enumerate(x)]
            offset = d + 1
            for i in range(d):
                for j in range(i, d):
                    terms.append(mul(f'theta[{offset}]', mul(x[i], x[j])))
                    offset += 1
            score = linear(terms)
        else:
            offset = 0
            for layer, (width, outputs) in enumerate(zip(spec['layers'], spec['layers'][1:])):
                following = []
                for _ in range(outputs):
                    score = linear([f'theta[{offset + width}]'] + [mul(f'theta[{offset + j}]', v) for j, v in enumerate(x)])
                    offset += width + 1
                    following.append(mul(score, score) if layer < len(spec['layers']) - 2 else score)
                x = following
            score = x[0]
        scores.append(score)
    return lines, scores


def generate_circuit(spec: dict, config: dict, directory: Path) -> dict:
    model = generate_model(spec, config['workload_seed'])
    p = len(model.parameters)
    n, d = config['sample_size'], model.layers[0]
    partition_size = config['population_size'] // 4
    depth = partition_size.bit_length() - 1
    bits = model.bounds()[-1]['signed_bits']
    if partition_size < 2 or partition_size & (partition_size - 1) or bits >= 63:
        raise ValueError('unsupported partition size or integer accumulator width')
    rules = policy(config)
    directory.mkdir(parents=True, exist_ok=True)
    library = str(LIB / 'poseidon.circom')
    lines = ['pragma circom 2.0.0;', f'include "{library}";', '''template Bits(n) {
 signal input in;
 signal output out[n];
 var acc = 0;
 for (var i=0; i<n; i++) {
  out[i] <-- (in >> i) & 1;
  out[i] * (out[i]-1) === 0;
  acc += out[i] * (2**i);
 }
 in === acc;
}
template Fold(n, domain) {
 signal input in[n];
 signal output out;
 var blocks = (n+14)\\15;
 signal state[blocks+1];
 state[0] <== domain*1000000000+n;
 component hashes[blocks];
 for (var k=0; k<blocks; k++) {
  hashes[k] = Poseidon(16);
  hashes[k].inputs[0] <== state[k];
  for (var j=0; j<15; j++) {
   if (15*k+j<n) { hashes[k].inputs[j+1] <== in[15*k+j]; }
   else { hashes[k].inputs[j+1] <== 0; }
  }
  state[k+1] <== hashes[k].out;
 }
 out <== state[blocks];
}
template Ternary() {
 signal input in;
 signal tmp;
 tmp <== in*(in-1);
 tmp*(in+1) === 0;
}
template Cert() {''',
             f'signal input theta[{p}];', 'signal input modelNonce;',
             f'signal input x[{n*d}];', f'signal input y[{n}];',
             f'signal input attribute[{n}];', f'signal input nonce[{n}];',
             f'signal input paths[{n*depth}];', f'signal input prediction[{n}];',
             'signal input tag;', 'signal input commitment;', 'signal input roots[4];',
             f'signal input indices[{n}];', 'signal output accepted;', 'signal output sessionBinding;',
             f'component modelHash = Fold({p+1}, 1);',
             f'for (var j=0; j<{p}; j++) {{ modelHash.in[j] <== theta[j]; }}',
             f'modelHash.in[{p}] <== modelNonce;', 'modelHash.out === commitment;',
             f'component tr[{p}]; for (var j=0;j<{p};j++) {{ tr[j]=Ternary(); tr[j].in <== theta[j]; }}',
             f'component xr[{n*d}]; for (var j=0;j<{n*d};j++) {{ xr[j]=Ternary(); xr[j].in <== x[j]; }}']
    ops, scores = arithmetic(spec, n, 'circom')
    lines += ops
    for row, score in enumerate(scores):
        g = int(row >= n // 2)
        lines += [f'component sign{row} = Bits({bits});',
                  f'sign{row}.in <== {score} + {2**(bits-1)};',
                  f'prediction[{row}] === sign{row}.out[{bits-1}];',
                  f'y[{row}]*(y[{row}]-1) === 0;', f'attribute[{row}]*(attribute[{row}]-1) === 0;',
                  f'component index{row} = Bits({depth+1});',
                  f'index{row}.in <== indices[{row}] - {g*partition_size*2};',
                  f'component leaf{row} = Fold({d+6}, 2);',
                  f'leaf{row}.in[0] <== index{row}.out[{depth}];', f'leaf{row}.in[1] <== {g};',
                  f'leaf{row}.in[2] <== indices[{row}]-{g*partition_size*2}-{partition_size}*index{row}.out[{depth}];',
                  f'leaf{row}.in[3] <== nonce[{row}];']
        lines += [f'leaf{row}.in[{4+j}] <== x[{row*d+j}];' for j in range(d)]
        lines += [f'leaf{row}.in[{d+4}] <== y[{row}];', f'leaf{row}.in[{d+5}] <== attribute[{row}];']
        previous = f'leaf{row}.out'
        for level in range(depth):
            prefix = f'path{row}_{level}'
            sibling = f'paths[{row*depth+level}]'
            bit = f'index{row}.out[{level}]'
            lines += [f'component {prefix} = Poseidon(2);',
                      f'{prefix}.inputs[0] <== {previous} + {bit}*({sibling}-{previous});',
                      f'{prefix}.inputs[1] <== {sibling} + {bit}*({previous}-{sibling});']
            previous = prefix+'.out'
        lines += [f'{previous} === roots[{2*g}]+index{row}.out[{depth}]*(roots[{2*g+1}]-roots[{2*g}]);',
                  f'signal correct{row}; correct{row} <== 1-y[{row}]-prediction[{row}]+2*y[{row}]*prediction[{row}];',
                  f'signal violation{row}; violation{row} <== attribute[{row}]*prediction[{row}];']
    for g in range(2):
        begin, end = g*(n//2), (g+1)*(n//2)
        correct = '+'.join(f'correct{row}' for row in range(begin, end))
        bad = '+'.join(f'violation{row}' for row in range(begin, end))
        countbits = (n//2).bit_length()+1
        lines += [f'component correctRange{g} = Bits({countbits});',
                  f'correctRange{g}.in <== ({correct})-{rules["required_correct_per_stratum"]};',
                  f'component violationRange{g} = Bits({countbits});',
                  f'violationRange{g}.in <== {rules["allowed_violations_per_stratum"]}-({bad});']
    lines += ['component tagHash = Poseidon(2); tagHash.inputs[0] <== tag; tagHash.inputs[1] <== commitment; sessionBinding <== tagHash.out;', 'accepted <== 1;', '}',
              'component main {public [tag, commitment, roots, indices]} = Cert();']
    path = directory / 'cert.circom'
    path.write_text('\n'.join(lines)+'\n')
    layout = {'theta': p, 'modelNonce': 1, 'x': n*d, 'y': n, 'attribute': n, 'nonce': n,
              'paths': n*depth, 'prediction': n}
    return {'parameter_count': p, 'depth': depth, 'score_bits': bits, 'layout': layout, 'policy': rules}
