# Ubuntu system efficiency status

The implementation, one complete ten-model attempt, result export and public verification have been completed. Under the fixed 180-second stage timeout and 10-GiB aggregate RSS budget, LR-D8 completed certification; five models timed out in Groth16 setup and four larger models exceeded the compilation memory budget. Failed rows are retained, and no missing performance value is estimated.

The measured implementation is commit 442f55e. Later packaging and input-validation changes do not alter the measured certification computations. All raw runs retain the measured source commit and source file digests. The independent small-relation acceptance check passed before formal measurement; twenty regression tests pass.

Formal configuration: N=1024, m=128, two holders, two equal strata, three MASCOT processes, three Groth16/REP3 provers, exact integer arithmetic, quadratic MLP activations, one session per model and workload seed 20261105. Each stratum requires at least 60 correct predictions and at most 4 violations. SRS files are checksum-verified public ceremony artifacts; setup does not claim SRS generation. The end-to-end security assumptions include at most one passive corruption and trusted local file handoff.

Local measurements and full logs: results/system_efficiency_final. Public records and tables: docs/experiment_results. The public LR-D8 passport, expected registration/transcript and verification key can be independently verified without private inputs. The single-prover control has also been verified after all measurements.

LR-D8 has 330,994 constraints and 2,570 private inputs. Its measured Setup is 211.832 seconds, end-to-end time 148.183 seconds and first-use total 360.017 seconds. These are one-run observations, not averages over repeated sessions; sample standard deviation is unavailable. No comparative scaling claim is made from failed model attempts.

TIMEOUT in Groth16 setup: LR-D16, LR-D64, MLP-D16-H8, MLP-D16-H8,4 and polynomial SVM-D16,2. OOM during Circom compilation: LR-D256 and LR-D1024. OOM during MP-SPDZ compilation: MLP-D128-H64 and MLP-D256-H128,64. OOM denotes the enforced observed aggregate RSS budget, not an assertion that the guest OS exhausted all physical memory.

See system_relation.md for protocol and timer boundaries, ubuntu_reproduction.md for tool installation and rerun commands, toolchain_lock.json for actual tool hashes, and experiment_restarts.json for the separately archived aborted attempts. All formal tables use only the final batch. Private model/data files, complete witnesses, shares, TLS private keys and large generated artifacts remain local and ignored by Git.
