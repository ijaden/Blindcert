# Ubuntu system efficiency status

The continuous certification implementation passes its normal-path functional acceptance check. Formal model measurements are pending. The functional check is explicitly excluded from paper table export.

The implemented path performs owner and full-population holder registration, three-party Commit-Reveal, private MASCOT evaluation, MAC-checked share export, per-party BN254-to-REP3 conversion, collaborative witness preparation, collaborative Groth16 proving, public packaging and independent verification. The verifier checks the separately retained registration, challenge, sampled indices and full expected public vector. Single-prover controls run in a separate directory after the session and first-use timers have stopped.

The generated circuit covers model commitments, full-root membership paths, bounded integer inference, predictions, both stratified accuracy and violation counters, and a session binding. All ten model architectures use the same circuit generator, MPC expression generator and runtime. See system_relation.md for exact encoding, security assumptions and timing boundaries.

Formal configuration is N=1024, m=128, two equal strata, two holders, three MASCOT parties, three REP3 provers, one session, fixed workload seed 20261105, zero-scale exact integer arithmetic, and identical model-independent resource budgets. Each stratum requires at least 60 correct predictions and at most 4 violations. The resource budget is 180 seconds per subprocess stage, 10 GiB aggregate subprocess-tree RSS and SRS power at most 21. These caps are explicit experiment limits; failures are retained rather than estimated.

The normal-path acceptance result is results/system_functional_check5/summary.json. It used N=16 and m=4, matching O2 optimization in both circuit compilers, and accepted the actual proof generated from MASCOT-derived shares. The separate integer-reference single-prover control produced the identical public vector. Earlier failed TLS and successful O1 checks remain archived in separate directories. Twenty tests pass.

Commands:

```bash
python3 scripts/run_efficiency_benchmark.py --config configs/system_efficiency.yaml --preflight
python3 scripts/run_efficiency_benchmark.py --config configs/system_efficiency.yaml --iterations 1 --output results/system_efficiency_measured
python3 scripts/export_latex_table.py --input results/system_efficiency_measured/summary.json --output results/system_efficiency_measured/tables
```

The larger-model and full-protocol scripts delegate to the same runtime. A real-backend failure does not switch to a mock or a clear-witness split. The legacy component benchmark requires an explicit flag and is excluded from system results.

Private model/data inputs, witnesses, shares, credentials, TLS private keys and large generated artifacts remain ignored by Git. Only source, configuration and public audit summaries are uploaded. Work uses branch experiment/system-e2e-three-party and retains the upstream history.
