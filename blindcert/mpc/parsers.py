from __future__ import annotations

import re


def parse_seconds(log: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}\s*[:=]\s*([0-9.]+)", log)
    return float(match.group(1)) if match else None


def parse_communication_bytes(log: str) -> int | None:
    match = re.search(r"communication\s*[:=]\s*([0-9]+)\s*bytes", log, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"Global data sent\s*=\s*([0-9.]+)\s*MB", log, re.IGNORECASE)
    if match:
        return int(float(match.group(1)) * 1_000_000)
    match = re.search(r"Data sent\s*=\s*([0-9.]+)\s*MB", log, re.IGNORECASE)
    return int(float(match.group(1)) * 1_000_000) if match else None


def parse_time_seconds(log: str) -> float | None:
    match = re.search(r"Time\s*=\s*([0-9.]+)\s*seconds", log)
    return float(match.group(1)) if match else None


def parse_policy_pass(log: str) -> bool | None:
    match = re.search(r"BLINDCERT_MPC_POLICY_PASS=([01])", log)
    return bool(int(match.group(1))) if match else None
