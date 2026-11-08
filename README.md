# BlindCert 

For the continuous three-party Ubuntu certification experiment, see [the reproduction instructions](docs/ubuntu_reproduction.md) and [the certification relation](docs/system_relation.md). The configuration-driven system entry is `scripts/run_efficiency_benchmark.py --config configs/system_efficiency.yaml`; legacy mock and component outputs are not system measurements.

This repository is an experimental, reproducible prototype for BlindCert: public
verification of certification over private models and benchmark partitions.

The implementation includes executable Python semantics, deterministic
quantized inference, mock backends for tests, and real adapter paths for
MP-SPDZ and co-circom collaborative proving. No command fabricates benchmark

## Quick start

```bash
python -m pytest
python -m blindcert.cli run-end-to-end --config configs/logistic_regression.yaml
python -m blindcert.cli evaluate --backend mpspdz --config configs/logistic_regression.yaml
python -m blindcert.cli adversarial-tests
python -m blindcert.cli export-results
```

From the repository root:

```bash
cd blindcert
python -m blindcert.cli prepare-data --config configs/logistic_regression.yaml
python -m blindcert.cli train --config configs/logistic_regression.yaml
python -m blindcert.cli benchmark --config configs/logistic_regression.yaml --dry-run
```

## Trust boundaries

- `MockMPCBackend` is only for deterministic tests. It reconstructs plaintext
  inputs inside one process and must not be used as a privacy claim.
- `MockProofBackend` is insecure plumbing. It signs the canonical public
  statement with deterministic hashes so tests can verify binding behavior.
- `MPSPDZBackend` runs the bundled MP-SPDZ `mascot` binary for logistic
  regression and opens only the final policy pass bit.
- `CollaborativeProofBackend` invokes the bundled `co-circom` binary. It
  requires real Circom artifacts and witness shares:

```bash
python -m blindcert.cli prove \
  --backend collaborative \
  --zkey path/to/circuit.zkey \
  --vk path/to/verification_key.json \
  --witness-share party0.toml:party0.wtns.share \
  --witness-share party1.toml:party1.wtns.share \
  --witness-share party2.toml:party2.wtns.share
```
