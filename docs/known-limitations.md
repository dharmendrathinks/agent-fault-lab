# Known limitations of v0.1

- This is one synthetic create/read workflow, one dropped-write fault, and one
  prompt-level read-back treatment. It is not an agent framework or broad benchmark.
- Local results from one 4B quantized checkpoint do not generalize to other models,
  prompts, runtimes, languages, tasks, or deployment environments.
- The first 20-run comparison used a thinking-only checkpoint by mistake and was
  unscorable. The replacement smoke used one run per cell and exposed ID-copying
  failures. Neither establishes a safeguard winner.
- A lookup request is counted separately from correct verification. The model may
  mistype an ID or misunderstand a truthful response.
- The evaluator checks final SQLite state and one terminal claim. It does not prove
  causal history, semantic quality beyond the exact contract, or every natural-
  language statement made during a run.
- SQLite evidence and JSONL traces are local mutable files, not signed, tamper-proof,
  transactionally coupled, or crash-safe audit records.
- HTTP timeout is not hard process cancellation. There is no retry/idempotency,
  concurrency, crash recovery, resume, or duplicate-effect protection yet.
- The adapter trusts the local Ollama daemon and its metadata. Loopback restriction,
  cloud-disabled checks, and non-forwarded credentials are not an OS sandbox.
- Model metadata identity is checked for the approved baseline, but the digest is
  recorded rather than pinned. Model updates require review.
- Report regeneration validates saved JSON and rewrites Markdown; it deliberately
  does not re-open the database. It verifies presentation consistency, not the
  authenticity of the saved JSON.
- Python 3.12 is the only supported runtime in v0.1. Local verification is macOS;
  Linux status depends on the repository CI run. Windows is untested.
- No hosted provider, MCP server, dashboard, real integration, security benchmark,
  performance guarantee, or production support commitment is included.

See the [M04 live comparison](milestones/M04-live-comparison.md),
[checkpoint diagnosis](milestones/M04-qwen-diagnosis.md), and
[replacement smoke](milestones/M04-instruct-smoke.md) for the underlying evidence.
