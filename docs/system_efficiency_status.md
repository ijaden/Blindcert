# Ubuntu system efficiency implementation status

The complete experiment remains unfinished. No formal end-to-end measurement or paper tables have been produced. The default benchmark entry checks readiness and returns exit code 2 while the complete relation is unavailable. Legacy component measurements cannot populate the requested system tables.

The checkout retains upstream commit `0e480001c8712e4d96bd5216ee76b038acf895a4`. The original local directory is preserved separately. Work uses branch `experiment/system-e2e-three-party`.

## Completed work

The LR MASCOT backend now launches three actual party processes with separate input and persistence directories. P0 supplies the model and P1/P2 supply their respective holder records. It operates over the BN254 scalar field and exports three authenticated share files containing model inputs, sampled records and predictions. Masked openings and explicit MAC checks precede export; conversion is attempted only after every process exits successfully. These exported fields are not yet a complete certification witness.

The bridge decodes MP-SPDZ 0.4.3 persistence headers and Montgomery field elements, then serializes co-circom 0.9.0 REP3 inputs. Each conversion process reads its own additive share and its predecessor's share, without reconstructing the secret. A three-private-input multiplication self-check successfully generated and verified a real Groth16 proof from these shares. No clear witness, split-input or split-witness command was used in that self-check. It is a functional check, not a system performance experiment.

The security boundary is explicitly limited: MASCOT authentication is checked before the local file conversion; REP3 supports an honest majority with at most one passive corruption. Trusted local files and orchestration are assumed during handoff. The converter does not independently validate persisted MACs after arbitrary file modification, and does not provide active security for REP3. The self-check uses public example TLS keys and an insecure test SRS; these are not a deployment setup.

Ten deterministic private workloads have been generated under artifacts/system_workload. The Python reference uses exact integer arithmetic, quadratic hidden activations, a zero decision threshold and lexicographic SVM quadratic coefficients. Model exports contain 8,321 and 41,217 parameters for the largest two MLPs, respectively. Per-layer worst-case integer bounds are derived and recorded. Cross-backend equivalence remains unvalidated.

Legacy full-protocol execution now refuses to report success as a continuous session. Plaintext-witness proof fallbacks have been removed from both legacy full-protocol and efficiency scripts. A raw authenticated share descriptor is rejected by the existing plaintext passport path instead of being treated as a complete Witness.

## Configuration and reproducibility

The fixed configuration uses N=1024, m=128, three MASCOT parties, three REP3 provers, two holders, two strata, one session and seed 20261105. One session follows the explicit instruction in section 1 of the supplied plan. Resource limits are proposed budgets; fit has not been established. The VMware guest exposes eight vCPUs and approximately 16 GiB RAM. Physical-host allocation is not observable from the guest.

```bash
python3 scripts/run_efficiency_benchmark.py --config configs/system_efficiency.yaml --preflight
python3 scripts/check_share_bridge.py
python3 -m pytest -q
```

The bridge and real MPC tests require permission for local sockets. The bridge writes a fresh UUID directory under results/share_bridge, with per-party logs, private share files and a public result.json. The readiness check writes environment.json, effective_config.yaml, model_manifest.json and preflight.json under results/system_efficiency. It returns 2 while implementation blockers remain. Public evidence and tool binary hashes are saved in docs/system_efficiency_audit.json. No private inputs, witnesses, shares or keys are staged for Git.

## Remaining required implementation

1. Complete certification circuits with full-population membership paths, registered model commitments, sampled-index binding, matching arithmetic and a feasible statistical policy.
2. Export all circuit input fields from the same MASCOT session, integrate conversion and cooperative witness preparation, and check the result against the independent integer reference.
3. Connect public verification to the expected registered statement and transcript in an independent process.
4. Implement closed-interval Setup, session and first-use timing, per-process resource limits and isolated single-prover controls.
5. Run all ten models sequentially, retain actual failed rows, export the two tables from measured records, and publish final reproducibility results.

## Validation

Sixteen tests pass, including the updated three-party MASCOT test and integer model semantic checks. The isolated share-bridge self-check also passes. These results do not establish a complete BlindCert certification session.
