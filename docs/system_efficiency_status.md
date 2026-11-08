# Ubuntu system efficiency implementation status

The complete experiment is not implemented. No new end-to-end performance claims or paper tables have been produced. Existing component benchmark scripts do not satisfy this experiment and must not be used to populate its tables.

The checkout retains upstream commit `0e480001c8712e4d96bd5216ee76b038acf895a4`. The original local directory did not contain Git metadata and is preserved separately.

The configuration uses N=1024, m=128, three MASCOT parties, three REP3 provers, two holders, two strata, and one session per model. One session follows the explicit instruction in section 1 of the supplied plan; later five-session examples are superseded. Resource limits in the configuration are proposed budgets, not an assertion that the workload fits.

Run the readiness inspection using the existing local tools:

```bash
python3 scripts/preflight_system_efficiency.py \
  --config configs/system_efficiency.yaml \
  --toolchain-root /home/jaden/workspace/blindcert/external
```

Exit code 2 means implementation blockers remain. The command records environment.json, model_manifest.json, preflight.json and effective_config.yaml in results/system_efficiency. It does not start measurement. The manifest parameter counts describe the configured architectures, not measured R1CS sizes.

The guest exposes eight vCPUs, approximately 16 GiB RAM and VMware virtualization. The physical host's full allocation cannot be established from the guest.

## Required implementation before measuring

1. Export authenticated MASCOT shares over the BN254 scalar field and validate their MACs before conversion.
2. Implement a specified, tested conversion to REP3 with explicit security assumptions. Renaming share files or reconstructing a clear witness does not satisfy this requirement.
3. Implement the complete certification relation, including full-population membership proofs, matching model arithmetic, feasible policy and public statement binding.
4. Wire registration, challenge, MPC, conversion, witness preparation, proof, packaging and independent verification into one session with direct outer timing.
5. Validate the small-model normal path before running the model list. Implement an exporter that consumes only successful measurements and preserves failed rows.

The model list includes LR-D1024 and a 41,217-parameter quadratic MLP. These are configured scaling targets; their practical predictive utility has not been evaluated using the synthetic efficiency workload.

## Validation

The readiness inspection has run against the existing local toolchain. All ten architectures are marked NOT_IMPLEMENTED, and no timing fields are populated. The existing thirteen tests pass when CO_CIRCOM points to the installed binary; these tests do not validate the missing cross-protocol conversion or a real system session.
