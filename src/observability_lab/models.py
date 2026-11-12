"""Auditable trace and summary contracts."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SpanRecord(BaseModel):
    """One timed stage within an LLM request."""

    model_config = ConfigDict(allow_inf_nan=False)

    name: str
    latency_ms: float = Field(ge=0)
    status: Literal["ok", "error"] = "ok"


class TraceRecord(BaseModel):
    """Provider-independent observability record for one request."""

    model_config = ConfigDict(allow_inf_nan=False)

    trace_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    environment: str
    release: str
    user_id: str
    session_id: str
    model: str
    prompt: str
    output: str
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    status: Literal["ok", "error"]
    quality_score: float = Field(ge=0, le=1)
    spans: list[SpanRecord]
    tags: list[str] = Field(default_factory=list)


class MetricsSummary(BaseModel):
    """Small dashboard-ready aggregate over trace records."""

    requests: int
    error_rate: float
    total_tokens: int
    total_cost_usd: float
    quality_samples: int
    mean_quality: float | None
    p95_latency_ms: float
