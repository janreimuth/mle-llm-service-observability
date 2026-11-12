"""Local JSONL and Langfuse Python SDK v5 trace sinks."""

from pathlib import Path
from typing import Protocol

from langfuse import get_client, propagate_attributes

from observability_lab.models import TraceRecord


class TraceSink(Protocol):
    """Minimal export interface used by the demo pipeline."""

    def record(self, trace: TraceRecord) -> None: ...


class JsonlTraceSink:
    """Append complete records locally for deterministic analysis."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, trace: TraceRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(trace.model_dump_json() + "\n")


class LangfuseTraceSink:
    """Export observations and score only successful answers."""

    def __init__(self) -> None:
        self.client = get_client()

    def record(self, trace: TraceRecord) -> None:
        with (
            propagate_attributes(
                trace_name="support-request",
                user_id=trace.user_id,
                session_id=trace.session_id,
                version=trace.release,
                environment=trace.environment,
                tags=trace.tags,
                metadata={
                    "trace_id": trace.trace_id,
                    "environment": trace.environment,
                    "status": trace.status,
                },
            ),
            self.client.start_as_current_observation(
                as_type="span",
                name="support-request",
                input={"prompt_chars": len(trace.prompt)},
                level="ERROR" if trace.status == "error" else "DEFAULT",
                metadata={
                    "trace_id": trace.trace_id,
                    "release": trace.release,
                    "environment": trace.environment,
                    "simulated_latency_ms": trace.latency_ms,
                    "synthetic": True,
                },
            ) as root,
        ):
            for span in trace.spans:
                with self.client.start_as_current_observation(
                    as_type="span",
                    name=span.name,
                    level="ERROR" if span.status == "error" else "DEFAULT",
                    metadata={"latency_ms": f"{span.latency_ms:.2f}"},
                ) as child:
                    child.update(output={"status": span.status})

            with self.client.start_as_current_observation(
                as_type="generation",
                name="llm-generation",
                model=trace.model,
                input={"prompt_chars": len(trace.prompt)},
                level="ERROR" if trace.status == "error" else "DEFAULT",
            ) as generation:
                generation.update(
                    output={"output_chars": len(trace.output)},
                    usage_details={
                        "input": trace.input_tokens,
                        "output": trace.output_tokens,
                    },
                    cost_details={"total": trace.cost_usd},
                )
                if trace.status == "ok":
                    generation.score(
                        name="quality",
                        value=trace.quality_score,
                    )
            root.update(
                output={"status": trace.status, "output_chars": len(trace.output)}
            )
        self.client.flush()
