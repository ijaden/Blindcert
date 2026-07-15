from __future__ import annotations

import statistics


def summarize(values: list[float | None]) -> dict[str, float | None]:
    measured = [v for v in values if v is not None]
    if not measured:
        return {"mean": None, "median": None, "stdev": None, "min": None, "max": None}
    return {
        "mean": statistics.fmean(measured),
        "median": statistics.median(measured),
        "stdev": statistics.stdev(measured) if len(measured) > 1 else 0.0,
        "min": min(measured),
        "max": max(measured),
    }
