"""Keep unit tests independent of live-service settings before app imports."""

import os

os.environ.update(
    {
        "PYTHON_DOTENV_DISABLED": "1",
        "TRACE_SINK": "jsonl",
        "LANGFUSE_TRACING_ENABLED": "false",
        "LANGFUSE_PUBLIC_KEY": "",
        "LANGFUSE_SECRET_KEY": "",
    }
)
