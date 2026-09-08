# Known limitations

- This is one synthetic create/read workflow. v0.1 has a dropped-write fault and
  prompt-level read-back treatment; v0.2.0 adds the M06–M10 execution experiments.
  It is not an agent framework or broad benchmark.
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
- Evidence remains mutable and unauthenticated. M09 couples run checkpoints and
  events in one journal transaction; the task database is a separate transaction.
  M07's ledger reconciles repeated delivery of an operation ID, not repeated intent.
- HTTP timeout is not model-server cancellation. M08 terminates only its local
  allowlisted tool worker. M09 covers selected process crashes, not arbitrary
  power-loss, storage corruption, remote effects or external database mutation.
- M08/M09 admit one worker at a time. Cleanup reserves time but prioritizes confirmed
  exit over the time budget if OS scheduling or kill completion takes longer.
- M09 resumes only compatible journaled process runs. Source/package/configuration
  changes can require the original checkout; old v0.1/M06/M07 artifacts are not migrated.
- The maintainer confirmed Phase 2 review completion. Detailed reviewer notes are
  not included in the repository; this confirmation adds no new experimental evidence.
- The adapter trusts the local Ollama daemon and its metadata. Loopback restriction,
  cloud-disabled checks, and non-forwarded credentials are not an OS sandbox.
- Model metadata identity is checked for the approved baseline, but the digest is
  recorded rather than pinned. Model updates require review.
- Report regeneration validates saved JSON and rewrites Markdown; it deliberately
  does not re-open the database. It verifies presentation consistency, not the
  authenticity of the saved JSON.
- Python 3.12 is the supported runtime. Local verification is macOS; Linux status
  depends on CI for these exact changes. The new process runner uses Unix `flock`
  and inherited descriptors; Windows is unsupported.
- No hosted provider, MCP server, dashboard, production task integration, security benchmark,
  performance guarantee, or production support commitment is included.

Phase 3 uses a real pinned static SkillSpector integration, but its recommendation
is not a guarantee. The local synthetic corpus contains three attack fixtures it
admitted as SAFE; see [the actual smoke results](milestones/Phase3-static-smoke.md).
Skills are inert Markdown. Python socket blocking is not an OS sandbox, and the
scanner dependency code is trusted. There is no arbitrary third-party skill execution.

A scoped scenario controller supplies M12/M13 approval decisions; they are not
human decisions. “Delivered” records attachment to the durable agent conversation, not
provider receipt or obedience. Scripted clients deliberately follow reference or
cached titles; their results cannot establish model susceptibility or robustness.
M13 starts from controlled stale snapshots and supplied fixture history rather
than a concurrent collaborative-memory service. No Phase 3 live-model smoke has
run for v0.3.0; M12/M13 learning reviews remain pending. Publication uses the
documented offline/static evidence and does not imply those activities occurred.

See the [M04 live comparison](milestones/M04-live-comparison.md),
[checkpoint diagnosis](milestones/M04-qwen-diagnosis.md), and
[replacement smoke](milestones/M04-instruct-smoke.md) for the underlying evidence.

The [M14 studies](milestones/M14.md) use a compact repeated fixture
pilot, not a general accuracy benchmark. Workflow read-back can miss duplicates;
failed or uninspectable attempts remain in the inventory. Conservative crash-time
accounting can end a study before all cells run. Semantic admission requires
complete feasibility probes and does not turn a SAFE result into a security
guarantee. The local gateway supports a bounded text/structured-output subset;
unsupported requests fail explicitly. Offline semantic profiles are test doubles.

The [M15 audit](milestones/M15.md) covers 43 authored examples and twelve known
defects. Passing it does not prove that every evaluator defect is detectable.
Mutants run in disposable package copies; audit artifacts retain full grades and
assertion differences. Existing production grading and historical results remain
unchanged.

[M16](milestones/M16.md) compares the native loop with a real LangGraph 1.2.11 graph
in the same separately locked environment. It isolates orchestration, while
sharing single model/tool steps. It is not a completely independent tool stack.
Four scenarios are supported. Manual approval, resume and crash/restart parity
are explicitly unsupported. The worker uses a 450-second deadline, within the
study's remaining 1,800-second budget. Python network restrictions and process
termination do not establish an OS sandbox or undo committed writes. Real-graph
offline checks demonstrate machinery; a live framework comparison remains pending.
