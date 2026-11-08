# Ubuntu reproduction

The measured checkout is the experiment/system-e2e-three-party branch of https://github.com/ijaden/Blindcert. Use a fresh checkout and preserve the original history. Runtime dependencies require Python 3.11 or newer, PyYAML, OpenSSL, curl, stdbuf and the toolchain below. The measured guest has eight vCPUs and approximately 16 GiB RAM. The physical host's full configuration is not visible from the VMware guest.

Install the Python project with `python3 -m venv .venv` and `.venv/bin/python -m pip install -e .`. Install Ubuntu build dependencies needed by MP-SPDZ as described in that project's release instructions. The existing scripts/install_mpspdz_release.py and scripts/install_co_circom_release.py install MP-SPDZ 0.4.3 and co-circom 0.9.0. Check docs/toolchain_lock.json against the resulting archives and binaries.

Additional fixed dependencies:

- Circom 2.2.3: https://github.com/iden3/circom/releases/tag/v2.2.3. Place the Linux executable at external/circom.
- Node 24.18.0: https://nodejs.org/dist/v24.18.0/node-v24.18.0-linux-x64.tar.xz. Extract under external/.
- snarkjs 0.7.6: run the installed Node/npm with `npm install --prefix external --no-save snarkjs@0.7.6` and ensure external/node-v24.18.0-linux-x64/bin is on PATH.
- co-circom circuit sources: https://github.com/TaceoLabs/co-snarks/archive/refs/tags/co-circom-v0.9.0.tar.gz. Extract and rename the top-level directory to external/co-snarks-src. The Poseidon circuit and optimized parameters are read from co-circom/co-circom/examples/lib inside that source distribution.

This workspace reuses the previously installed toolchain through an ignored external symlink. A new checkout should install dependencies at the same relative layout instead. Generated Circom source resolves dependency paths from the current checkout at generation time; absolute paths in local artifacts are not portable and must be regenerated.

Generate all ten private workloads once, before registration or sampling:

```bash
python3 scripts/prepare_system_workload.py --config configs/system_efficiency.yaml
python3 scripts/run_efficiency_benchmark.py --config configs/system_efficiency.yaml --preflight
python3 scripts/run_efficiency_benchmark.py --config configs/system_efficiency.yaml --iterations 1 --output results/system_efficiency_measured_v2
python3 scripts/export_latex_table.py --input results/system_efficiency_measured_v2/summary.json --output results/system_efficiency_measured_v2/tables
```

Use new empty output directories when repeating a complete measurement. The preparation script refuses to overwrite an existing private workload directory. All formal models share N=1024, m=128, exact integer encoding and the fixed policy and resource limits in configs/system_efficiency.yaml. One measured session follows the explicit instruction in section 1 of the supplied plan; no five-run average is claimed. Compilation, SRS acquisition/checksum verification and Groth16 setup are measured from an empty per-model artifact directory. SRS cache reuse is recorded explicitly.

The original snarkjs release SRS URLs returned HTTP 403 in this environment. Current official snarkjs documentation links the same named files at https://circom.info/. The runtime verifies each file against the original release's BLAKE2b checksum before using it. This is acquisition and verification of an existing SRS, not SRS generation. The abandoned download-failure attempt is preserved at results/system_efficiency_measured and documented in experiment_restarts.json. No measurements from that attempt are merged into the replacement tables.

For functional acceptance on a small relation, use `python3 scripts/run_system_efficiency.py --functional-check --output results/system_functional_check_new`. It includes a full registration/challenge/MPC/conversion/witness/proof/verification path and an independent integer control. Its N/m and deliberately permissive functional-check policy differ from the formal experiment. Table export refuses functional-check summaries.

Private inputs, shares, witnesses, TLS private keys, downloaded dependencies and large proving artifacts remain local under ignored paths. Public summaries, source/configuration digests, toolchain locks, table files and reproduction documents can be committed. The verifier uses the public expected registration and transcript retained before proving; it does not read model parameters, records or witness shares.
