"""Aggregate traces and identify the most likely production issue."""

import math
import statistics
from pathlib import Path

from pydantic import ValidationError

from observability_lab.models import MetricsSummary, TraceRecord


def load_traces(path: Path) -> list[TraceRecord]:
    """Load one validated trace per JSONL line."""
    with path.open(encoding="utf-8") as file:
        traces = []
        for number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                traces.append(TraceRecord.model_validate_json(line))
            except ValidationError:
                # Identify the bad record without printing potentially private text.
                raise ValueError(f"Invalid trace at {path}:{number}") from None
        return traces


def summarize(traces: list[TraceRecord]) -> MetricsSummary:
    """Calculate dashboard metrics with a nearest-rank p95."""
    if not traces:
        raise ValueError("At least one trace is required")
    latencies = sorted(trace.latency_ms for trace in traces)
    p95_index = math.ceil(len(latencies) * 0.95) - 1
    quality_scores = [trace.quality_score for trace in traces if trace.status == "ok"]
    return MetricsSummary(
        requests=len(traces),
        error_rate=sum(trace.status == "error" for trace in traces) / len(traces),
        total_tokens=sum(trace.input_tokens + trace.output_tokens for trace in traces),
        total_cost_usd=round(sum(trace.cost_usd for trace in traces), 8),
        quality_samples=len(quality_scores),
        mean_quality=statistics.mean(quality_scores) if quality_scores else None,
        p95_latency_ms=latencies[p95_index],
    )


def diagnose(traces: list[TraceRecord]) -> list[str]:
    """Return evidence-backed incident observations in priority order."""
    summary = summarize(traces)
    findings: list[str] = []
    if summary.error_rate > 0.05:
        findings.append(f"High error rate: {summary.error_rate:.1%}")
    responses = [trace for trace in traces if trace.status == "ok"]
    low_quality = [trace for trace in responses if trace.quality_score < 0.5]
    if low_quality:
        findings.append(
            f"Low quality on {len(low_quality)} of {len(responses)} successful responses"
        )
    if summary.p95_latency_ms > 1000:
        findings.append(f"High p95 latency: {summary.p95_latency_ms:.0f} ms")
    return findings or ["No configured threshold is breached"]
