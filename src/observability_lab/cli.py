"""Command-line entry point for tracing and incident analysis."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from observability_lab.analysis import diagnose, load_traces, summarize
from observability_lab.pipeline import run_demo
from observability_lab.recorder import JsonlTraceSink, LangfuseTraceSink


def positive_int(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the LLM observability demo.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("run-demo")
    demo.add_argument("--count", type=positive_int, default=10)
    demo.add_argument(
        "--sink",
        choices=["jsonl", "langfuse"],
        default=os.getenv("TRACE_SINK", "jsonl"),
    )
    for name in ("summarize", "diagnose"):
        command = subparsers.add_parser(name)
        command.add_argument(
            "--path", type=Path, help="Analyze this JSONL file explicitly"
        )
    args = parser.parse_args()
    path = Path(os.getenv("TRACE_PATH", "data/generated/traces.jsonl"))

    if args.command == "run-demo":
        if args.sink not in {"jsonl", "langfuse"}:
            parser.error("TRACE_SINK must be jsonl or langfuse")
        if args.sink == "jsonl":
            resolved = path.resolve()
            generated_dir = Path.cwd() / "data/generated"
            if resolved == Path("data/sample_traces.jsonl").resolve():
                parser.error(
                    "TRACE_PATH must not overwrite the supplied incident dataset"
                )
            replaceable = path.is_file() and resolved in {
                generated_dir / "traces.jsonl",
                generated_dir / "walkthrough.jsonl",
            }
            if path.is_symlink() or (path.exists() and not replaceable):
                parser.error("TRACE_PATH must point to a new file or a lab output file")
            if replaceable:
                path.unlink()
            sink = JsonlTraceSink(path)
        else:
            sink = LangfuseTraceSink()
        records = run_demo(
            sink,
            args.count,
            environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "development"),
            release=os.getenv("LANGFUSE_RELEASE", "local"),
        )
        if args.sink == "langfuse":
            print(
                f"Processed {len(records)} traces locally. Verify receipt in Langfuse."
            )
        else:
            print(f"Recorded {len(records)} traces with jsonl")
        return

    try:
        traces = load_traces(
            args.path or (path if path.exists() else Path("data/sample_traces.jsonl"))
        )
        if args.command == "summarize":
            print(summarize(traces).model_dump_json(indent=2))
        else:
            print("\n".join(f"- {finding}" for finding in diagnose(traces)))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
