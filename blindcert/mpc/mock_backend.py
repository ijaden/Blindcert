from __future__ import annotations

from blindcert.plaintext.evaluator import evaluate
from blindcert.types import MPCConfig, MPCResult, PublicStatement, Share, Witness, WitnessShare


class MockMPCBackend:
    """Deterministic insecure MPC test double.

    It reconstructs model and records inside one process and is only suitable
    for unit and integration tests.
    """

    backend_id = "mock"

    def setup(self, config: MPCConfig) -> None:
        if config.backend_id != self.backend_id:
            raise ValueError("MockMPCBackend received incompatible config")

    def evaluate(
        self,
        public_statement: PublicStatement,
        model_shares: list[Share],
        benchmark_shares: list[Share],
    ) -> MPCResult:
        opening = model_shares[0].value
        payload = benchmark_shares[0].value
        model = payload["model"]
        policy = payload["policy"]
        witness_records = payload["witness_records"]
        records = [wr.record for wr in witness_records]
        predictions, metrics = evaluate(model, records, policy)
        witness = Witness(
            model_opening=opening,
            records=witness_records,
            predictions=predictions,
            metrics=metrics,
            policy_id=public_statement.pid,
            sid=public_statement.sid,
        )
        return MPCResult(
            ok=bool(metrics.policy_passed),
            witness_shares=[WitnessShare(witness)],
            preprocessing_seconds=None,
            online_seconds=None,
            communication_bytes=None,
            peak_memory_bytes=None,
            raw_logs={"backend": self.backend_id, "status": "mocked"},
        )
