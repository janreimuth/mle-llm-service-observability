"""Tests for local metrics and incident diagnosis."""

from pathlib import Path

import pytest

from observability_lab.analysis import diagnose, load_traces, summarize

SAMPLE_PATH = Path("data/sample_traces.jsonl")


def test_summary_aggregates_every_trace() -> None:
    summary = summarize(load_traces(SAMPLE_PATH))

    assert summary.requests == 6
    assert summary.error_rate == pytest.approx(1 / 6)
    assert summary.p95_latency_ms == 1450
    assert summary.total_tokens == 317
    assert summary.quality_samples == 5


def test_diagnosis_identifies_service_and_quality_failures() -> None:
    findings = diagnose(load_traces(SAMPLE_PATH))

    assert any("error rate" in finding for finding in findings)
    assert any("quality" in finding for finding in findings)
    assert any("latency" in finding for finding in findings)
    assert any("2 of 5 successful responses" in finding for finding in findings)


def test_provider_failures_do_not_count_as_generated_answers() -> None:
    traces = [trace for trace in load_traces(SAMPLE_PATH) if trace.status == "error"]
    summary = summarize(traces)
    assert summary.error_rate == 1
    assert summary.quality_samples == 0
    assert summary.mean_quality is None
    assert not any("Low quality" in finding for finding in diagnose(traces))
