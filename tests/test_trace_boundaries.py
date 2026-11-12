"""Keep synthetic evidence consistent and exports private."""

from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from observability_lab.cli import main
from observability_lab.models import SpanRecord, TraceRecord
from observability_lab.pipeline import deterministic_trace
from observability_lab.recorder import LangfuseTraceSink


def test_stages_sum_to_the_total_and_errors_have_zero_quality():
    for index in range(100):
        trace = deterministic_trace("question", index)
        assert sum(span.latency_ms for span in trace.spans) == trace.latency_ms
        if trace.status == "error":
            assert trace.quality_score == 0


@pytest.mark.parametrize("index,quality", [(0, 0.9), (0, 0.0), (6, 0.0)])
def test_root_updated_before_closing_and_no_raw_text_export(
    monkeypatch, index, quality
):
    calls = []

    class Observation:
        active = True

        def update(self, **values):
            assert self.active
            calls.append(values)

        def score(self, **values):
            assert self.active
            calls.append(values)

    class Client:
        @contextmanager
        def start_as_current_observation(self, **values):
            calls.append(values)
            observation = Observation()
            yield observation
            observation.active = False

        def flush(self):
            pass

    monkeypatch.setattr("observability_lab.recorder.get_client", lambda: Client())
    monkeypatch.setattr(
        "observability_lab.recorder.propagate_attributes",
        lambda **kwargs: empty_context(),
    )
    trace = deterministic_trace("private customer content", index)
    trace.quality_score = quality
    LangfuseTraceSink().record(trace)
    assert trace.prompt not in repr(calls)
    assert trace.output not in repr(calls)
    assert any(call.get("level") == "ERROR" for call in calls) == (
        trace.status == "error"
    )
    scores = [call for call in calls if call.get("name") == "quality"]
    assert scores == (
        [{"name": "quality", "value": quality}] if trace.status == "ok" else []
    )
    assert any(
        call.get("metadata", {}).get("simulated_latency_ms") == trace.latency_ms
        for call in calls
    )


@contextmanager
def empty_context():
    yield


def test_summarize_empty_input_is_explicit():
    from observability_lab.analysis import summarize

    with pytest.raises(ValueError, match="At least one trace"):
        summarize([])


def test_invalid_sink_environment_does_not_silently_write_jsonl(monkeypatch):
    monkeypatch.setenv("TRACE_SINK", "typo")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr("sys.argv", ["observability-lab", "run-demo"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


@pytest.mark.parametrize("name", ["traces.jsonl", "walkthrough.jsonl"])
def test_rerun_replaces_lab_output(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "generated" / name
    monkeypatch.setenv("TRACE_PATH", str(path))
    monkeypatch.setattr("sys.argv", ["observability-lab", "run-demo", "--count", "1"])

    main()
    main()

    assert len(path.read_text().splitlines()) == 1


def test_custom_trace_file_can_be_created_but_not_overwritten(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "data" / "generated" / "custom.jsonl"
    monkeypatch.setenv("TRACE_PATH", str(path))
    monkeypatch.setattr("sys.argv", ["observability-lab", "run-demo", "--count", "2"])
    main()
    original = path.read_bytes()

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert "TRACE_PATH" in capsys.readouterr().err
    assert path.read_bytes() == original


def test_cloud_demo_does_not_claim_delivery_or_touch_jsonl(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "existing.jsonl"
    path.write_text("keep this")
    monkeypatch.setenv("TRACE_PATH", str(path))
    monkeypatch.setattr(
        "sys.argv",
        ["observability-lab", "run-demo", "--sink", "langfuse", "--count", "1"],
    )
    exported = []

    class Sink:
        def record(self, trace):
            exported.append(trace)

    monkeypatch.setattr("observability_lab.cli.LangfuseTraceSink", Sink)
    main()

    assert len(exported) == 1
    assert (
        "Processed 1 traces locally. Verify receipt in Langfuse."
        in capsys.readouterr().out
    )
    assert path.read_text() == "keep this"


@pytest.mark.parametrize("field", ["latency_ms", "cost_usd"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_metrics_must_be_finite(field, value):
    data = deterministic_trace("question", 0).model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        TraceRecord.model_validate(data)
    with pytest.raises(ValidationError):
        SpanRecord(name="stage", latency_ms=value)


def test_bad_trace_identifies_line_without_exposing_content(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "bad.jsonl"
    path.write_text('\n{"private-customer-text": invalid}\n')
    monkeypatch.setattr(
        "sys.argv", ["observability-lab", "summarize", "--path", str(path)]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert f"{path}:2" in message
    assert "private-customer-text" not in message
