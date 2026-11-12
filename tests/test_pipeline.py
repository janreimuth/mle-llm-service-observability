"""Tests for trace creation and local recording."""

from pathlib import Path

from observability_lab.analysis import load_traces
from observability_lab.pipeline import deterministic_trace, run_demo
from observability_lab.recorder import JsonlTraceSink


def test_trace_contains_nested_stage_evidence() -> None:
    trace = deterministic_trace("question", 0)

    assert [span.name for span in trace.spans] == [
        "retrieve-context",
        "generate-answer",
    ]
    assert trace.input_tokens > 0


def test_demo_writes_valid_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"

    run_demo(JsonlTraceSink(path), count=4)

    assert len(load_traces(path)) == 4


def test_trace_identity_distinguishes_release_and_environment() -> None:
    baseline = deterministic_trace("question", 0)
    assert baseline.trace_id == deterministic_trace("question", 0).trace_id
    assert (
        len(
            {
                baseline.trace_id,
                deterministic_trace("question", 0, release="v2").trace_id,
                deterministic_trace("question", 0, environment="production").trace_id,
            }
        )
        == 3
    )
