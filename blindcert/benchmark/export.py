from __future__ import annotations

import csv
import json
from dataclasses import fields
from pathlib import Path

from blindcert.policy import statistical_delta
from blindcert.serialization import to_canonical
from blindcert.types import BenchmarkResult, CertificationPolicy


def write_jsonl(path: str | Path, results: list[BenchmarkResult]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(to_canonical(result), sort_keys=True) + "\n")


def write_csv(path: str | Path, results: list[BenchmarkResult]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    names = [field.name for field in fields(BenchmarkResult)]
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, names)
        writer.writeheader()
        for result in results:
            writer.writerow(to_canonical(result))


def write_placeholder_benchmark_table(path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "\\begin{tabular}{lrrrrr}\n"
        "\\hline\n"
        "Model & $m$ & MPC (s) & Proof (s) & Comm. (GB) & Verify (ms) \\\\\n"
        "\\hline\n"
        "Logistic regression & 128 & -- & -- & -- & -- \\\\\n"
        "Logistic regression & 512 & -- & -- & -- & -- \\\\\n"
        "MLP                 & 128 & -- & -- & -- & -- \\\\\n"
        "MLP                 & 512 & -- & -- & -- & -- \\\\\n"
        "Compact CNN         & 128 & -- & -- & -- & -- \\\\\n"
        "Compact CNN         & 512 & -- & -- & -- & -- \\\\\n"
        "\\hline\n"
        "\\end{tabular}\n",
        encoding="utf-8",
    )


def write_statistical_table(path: str | Path, policy: CertificationPolicy) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "\\begin{tabular}{lrrrr}",
        "\\hline",
        "Stratum & $N_g$ & $m_g$ & $\\epsilon_g$ & $\\delta_g$ \\\\",
        "\\hline",
    ]
    total_delta = 0.0
    for stratum_id, sp in sorted(policy.strata.items()):
        delta = statistical_delta(sp.population_size, sp.sample_size, sp.epsilon)
        total_delta += delta
        lines.append(
            f"{stratum_id} & {sp.population_size} & {sp.sample_size} & "
            f"{sp.epsilon:.6g} & {delta:.6g} \\\\"
        )
    lines.extend(["\\hline", f"All & -- & -- & -- & {total_delta:.6g} \\\\", "\\hline", "\\end{tabular}"])
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_placeholder_results(root: str | Path, policy: CertificationPolicy) -> None:
    root = Path(root)
    write_jsonl(root / "results/raw/placeholder.jsonl", [])
    write_csv(root / "results/processed/results.csv", [])
    write_csv(root / "results/processed/summary.csv", [])
    write_placeholder_benchmark_table(root / "results/tables/benchmark_table.tex")
    write_statistical_table(root / "results/tables/statistical_table.tex", policy)
