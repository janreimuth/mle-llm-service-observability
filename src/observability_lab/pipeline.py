"""Deterministic traced workflow with retrieval and generation stages."""

import hashlib
import json

from observability_lab.models import SpanRecord, TraceRecord
from observability_lab.recorder import TraceSink


def deterministic_trace(
    prompt: str,
    index: int,
    environment: str = "development",
    release: str = "local",
) -> TraceRecord:
    """Create a stable request trace with controlled healthy and failing cases."""
    degraded = index % 5 == 4
    error = index % 7 == 6
    input_tokens = max(4, len(prompt.split()) * 2)
    output_tokens = 18 if not error else 0
    latency = 220 + (index % 4) * 90 + (850 if degraded else 0)
    quality = 0 if error else (0.35 if degraded else 0.9)
    output = "Provider unavailable" if error else f"Grounded answer for: {prompt}"
    identity = json.dumps([environment, release, prompt, index])
    trace_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return TraceRecord(
        trace_id=trace_id,
        environment=environment,
        release=release,
        user_id=f"user-{index % 3}",
        session_id=f"session-{index // 2}",
        model="openai/gpt-oss-20b",
        prompt=prompt,
        output=output,
        latency_ms=latency,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round((input_tokens * 0.15 + output_tokens * 0.6) / 1_000_000, 8),
        status="error" if error else "ok",
        quality_score=quality,
        spans=[
            SpanRecord(name="retrieve-context", latency_ms=35 + (index % 5) * 2),
            SpanRecord(
                name="generate-answer",
                latency_ms=latency - (35 + (index % 5) * 2),
                status="error" if error else "ok",
            ),
        ],
        tags=["support", "degraded" if degraded else "baseline"],
    )


def run_demo(
    sink: TraceSink,
    count: int = 10,
    environment: str = "development",
    release: str = "local",
) -> list[TraceRecord]:
    """Record a compact dataset with enough variation for diagnosis."""
    records = [
        deterministic_trace(
            f"How do I resolve support case {index % 4}?",
            index,
            environment=environment,
            release=release,
        )
        for index in range(count)
    ]
    for record in records:
        sink.record(record)
    return records
