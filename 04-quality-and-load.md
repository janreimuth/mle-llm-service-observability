# Quality Evaluation And Load Evidence

**Operational health** describes whether the service is up, fast, and free
of errors. **Answer quality** describes whether the answers are correct and
useful. The two are independent: a fast `200` response can still be wrong,
while a correct response can violate latency objectives. Production
**sampling**, exporting only a fraction of traces, controls observability
volume and cost but can hide rare failures if it is too aggressive.

In this last lesson you separate the kinds of evidence you have collected,
write an automated quality check, test what sampling does to rare failures,
and finish with an operational recommendation for the incident from
lesson 03.

## Three Kinds Of Evidence

Each kind of evidence answers a different question:

| Evidence | Question it answers | Example from this course | What it cannot establish |
|---|---|---|---|
| Successful throughput, HTTP error rate, and p95 from a load test | How did the API handle this workload? | The deployment repo's [baseline](https://github.com/neuefische/mle-containerized-llm-deployment/blob/main/03-scaling-and-failures.md#establish-a-baseline): 0% errors and a p95 of about 11 ms | Whether the returned text was correct. |
| Stage timings and status for one trace | Where did this request spend time or fail? | `sample-03`: generation takes 1,395 of 1,450 ms | Which change caused a release-level regression. |
| Score and number of successful responses scored | How did outputs perform under this rubric? | `v1.1.0`: mean quality 0.53 over 3 answers | Factuality, if the rubric only checks format or keywords. |

A **load test** sends many requests at once to measure how a service copes;
**throughput** is the number of requests it completes per second. A
**rubric** is the set of criteria a quality score is based on.

The incident data shows why health and quality need separate signals.
`sample-03` has `status: ok`, so a health check or load test would count it
as a success, yet its quality score is 0.31. `v1.1.0` fails one request in
four, which makes the release look mostly fine, but its mean quality dropped
from 0.91 to 0.53.

## Walk Through A Format Check

Answer quality can be evaluated in three common ways:

- **Deterministic checks** test format, required fields, or keywords. They
  are cheap and exact, but shallow.
- **LLM-as-judge** asks another model to rate the answer. It scales well,
  but the judge needs its own validation.
- **Human review** is the most reliable, but slow and expensive.

The `quality_score` values in this repository are synthetic stand-ins for
one of these. This section builds the first kind.

Imagine that responses must be JSON objects with a nonempty `answer` field.
Run the check on three example responses:

```bash
uv run python - <<'PY'
import json

for raw in ('{"answer":"Refund approved"}', '{"answer":""}', 'not JSON'):
    try:
        response = json.loads(raw)
    except json.JSONDecodeError:
        print(False)
        continue
    answer = response.get("answer") if isinstance(response, dict) else None
    print(isinstance(answer, str) and bool(answer.strip()))
PY
```

Expected: `True`, `False`, `False`. The first result only confirms the
format. There is no policy evidence here that the refund should be approved.
Call the check `answer_format_valid` and keep it separate from any review of
the answer's factual or policy support.

In production, a check like `answer_format_valid` is attached to each trace
as a score, like the `quality` score in lesson 02, so a dashboard can track
it per release.

## Sample Without Losing Failures

A busy service produces far more traces than anyone needs to store.
**Head sampling** decides at the start of each request, at random, whether
to keep its trace. The Langfuse SDK does this with `LANGFUSE_SAMPLE_RATE` in
`.env`: `1.0` keeps every trace, `0.2` keeps about one in five.

Random sampling treats every trace the same, so a rare failure is easy to
lose. Sample the ten walkthrough traces from lesson 01 at 20%, five times,
and compare it with a policy that keeps every error and samples only the
successes:

```bash
uv run python - <<'PY'
import random
from pathlib import Path

from observability_lab.analysis import load_traces

records = load_traces(Path("data/generated/walkthrough.jsonl"))


def describe(kept):
    errors = sum(record.status == "error" for record in kept)
    return f"kept {len(kept)} traces, {errors} errors"


for seed in range(5):
    rng = random.Random(seed)
    random_kept = [record for record in records if rng.random() < 0.2]
    rng = random.Random(seed)
    error_aware = [
        record for record in records if record.status == "error" or rng.random() < 0.2
    ]
    print(f"seed {seed}: random {describe(random_kept)} | error-aware {describe(error_aware)}")
PY
```

Expected output:

```text
seed 0: random kept 0 traces, 0 errors | error-aware kept 1 traces, 1 errors
seed 1: random kept 3 traces, 0 errors | error-aware kept 3 traces, 1 errors
seed 2: random kept 2 traces, 0 errors | error-aware kept 3 traces, 1 errors
seed 3: random kept 2 traces, 1 errors | error-aware kept 3 traces, 1 errors
seed 4: random kept 3 traces, 0 errors | error-aware kept 4 traces, 1 errors
```

Random sampling kept the only failure in one run out of five. The
error-aware policy kept it every time, while still dropping most successful
traces. Keeping every error requires deciding *after* the request finishes,
once its status is known. This is called **tail sampling**, and it needs
support in the tracing pipeline, unlike a simple sample rate.

## Exercise: Recommend An Operational Change

Bring the evidence from all four lessons together.

1. Extend the format check into `answer_has_source`, a check that passes
   only when the answer contains a `Source:` label. Test it with a passing
   case, a failing case, and an upstream error, where the provider failed and
   there is no response at all.

2. State the denominator of `answer_has_source`, and where the upstream
   error is counted instead.

3. Describe a sampling policy for the support assistant that keeps rare
   errors visible without exporting raw customer text.

4. Write a short operational recommendation for `v1.1.0`. Combine your
   incident note from lesson 03 with what you learned about quality and load
   evidence in this lesson, and state its limitations.

<details>
<summary>Show Reference Answers</summary>

**Step 1:** Return `None` for an upstream error, because there is no answer
to evaluate:

```bash
uv run python - <<'PY'
import json


def answer_has_source(raw):
    if raw is None:  # upstream error: there is no answer to evaluate
        return None
    try:
        response = json.loads(raw)
    except json.JSONDecodeError:
        return False
    answer = response.get("answer") if isinstance(response, dict) else None
    return isinstance(answer, str) and "Source:" in answer


for raw in (
    '{"answer":"Refunds take 5 days. Source: refund-policy"}',
    '{"answer":"Refunds take 5 days."}',
    None,
):
    print(answer_has_source(raw))
PY
```

Expected: `True`, `False`, `None`.

**Step 2:** The denominator is the successful answers that were evaluated.
An upstream error produced no answer, so it gets no score; it counts toward
the error rate instead.

**Step 3:** Keep every error trace with its metadata, and sample successful
traces at a fixed rate per release, so each release has enough samples for
its quality mean. Export only the fields lesson 01 marked as safe, with
lengths instead of raw text. Report the sample size and how traces were
selected, so the mean is interpretable.

**Step 4:** An example recommendation:

> Pause the rollout of `v1.1.0`. The release has a 25% error rate, a p95 of
> 1,450 ms, and mean quality of 0.53 against 0.91 on `v1.0.0`, with the
> slowdown in generation and one healthy request on the same release. A
> healthy load test would not have shown this, because the slow and weak
> answers still returned success. This is based on six synthetic traces and
> synthetic quality scores, and it shows an association with the release,
> not a confirmed cause.

</details>

## Clean Up

To reset the repo to a clean local state, for example before rerunning the
lessons from scratch, delete the generated walkthrough traces:

```bash
rm -rf data/generated
```

The incident file `data/sample_traces.jsonl` is sample data and stays. If
you exported traces to Langfuse, delete the demo project or its API keys in
Langfuse, and clear the `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`
values in `.env`.

## Check Your Understanding

1. Does valid JSON establish factual accuracy?
2. Can aggressive trace sampling hide a serious regression?
3. A load test shows 0% errors and a low p95. Can you conclude that users
   get good answers?

<details>
<summary>Show Reference Answers</summary>

1. No. It checks format, not semantic support or task correctness.
2. Yes, particularly for rare failures. Keep every error and sample only the
   successes, and state the sampling policy and the population represented
   by each metric.
3. No. A load test measures operational health: whether requests succeed
   and how fast. A response can succeed quickly and still be wrong, so
   answer quality needs its own checks.

</details>

## Further Reading

- Langfuse: [LLM-as-a-Judge](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge) /
  [Sampling](https://langfuse.com/docs/observability/features/sampling)
- OpenTelemetry: [Sampling](https://opentelemetry.io/docs/concepts/sampling/)
