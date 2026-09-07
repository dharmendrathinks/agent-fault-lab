# M04 — Qwen output-limit diagnosis, 2026-09-07

Historical diagnosis: the user subsequently approved replacement and removal of
the old model. See [the new Instruct smoke tests](M04-instruct-smoke.md); the
diagnostic probes and original comparison below have not been rewritten.

## Finding

At diagnosis, the installed `qwen3:4b` alias was **Qwen3-4B-Thinking-2507**, not the original
hybrid Qwen3-4B checkpoint whose thinking behavior can be switched off. Our earlier
assumption that `think=false` established a non-thinking baseline was incorrect.

Local `/api/show` metadata identifies:

```json
{
  "general.finetune": "Thinking",
  "general.version": "2507",
  "general.license.link": "https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507/blob/main/LICENSE"
}
```

Its recorded digest is
`359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
The [official Ollama tag list](https://ollama.com/library/qwen3/tags) associates
this digest prefix with its explicit 4B Thinking-2507 tag. The
[checkpoint's official model card](https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507)
documents thinking-only behavior and a template that opens a thinking block.
Generic Qwen3 family documentation is not enough to establish this checkpoint's
mode support.

## What was checked

- Re-ran the 22 offline adapter tests. The real SDK serialization test confirms
  that the outgoing JSON contains `think: false` and `num_predict: 512`. The SDK
  is not dropping the false boolean. This is a mocked transport test, not a
  claim that HTTP settings guarantee the model's behavior.
- Read the installed model's metadata and exact template without changing either.
- Inspected actual rendered prompts through Ollama 0.33.2's internal debug API.
  The normal read-back request ends in an open `<think>` block even with the
  false thinking flag. This debug endpoint is version-specific, not a public
  compatibility guarantee or a new production dependency.
- Ran three bounded, raw-HTTP first-response probes, preserving requests,
  responses and rendered prompts. They bypassed the Python SDK but used the same
  task, tool definitions, system/read-back instructions, local model, temperature
  and context size. No returned tool was executed; these are output diagnostics,
  not full task evaluations or additional M04 comparison trials.

| Diagnostic condition | Output budget | Actual output tokens | Result |
|---|---|---|---|
| Unchanged control | 512 | 512 | Length stop; no structured tool request |
| Only increase budget | 1,024 | 1,024 | Length stop; no structured tool request |
| Only add empty-thinking input prefix | 512 | 512 | Length stop; no structured tool request |

The prefix probe used an additional final assistant input containing an empty
thinking block. The debug response confirmed that the rendered input ended in
that closed block. This was an isolated diagnostic hypothesis based on the
[original hybrid checkpoint's template](https://huggingface.co/Qwen/Qwen3-4B/raw/main/tokenizer_config.json),
not a supported non-thinking switch for Thinking-2507. It failed and was **not**
added to the application. No model output was stripped or repaired.

An initial debug request used `debug_render_only` instead of Ollama's actual
`_debug_render_only` field. Ollama ignored it and generated one additional
512-token response. That response is retained; the probe stopped when debug
metadata was absent. After checking the
[versioned API definition](https://github.com/ollama/ollama/blob/v0.33.2/api/types.go),
the corrected probes used a separate directory. Total diagnostic generation was
four requests and 2,560 output tokens, not three requests. No hidden reruns or
overwrite of the mistaken request's evidence occurred.

## Interpretation

The known checkpoint identity explains why requesting non-thinking behavior was
the wrong setup assumption. The installed prompt opens the thinking block, and
the [versioned server implementation](https://github.com/ollama/ollama/blob/v0.33.2/server/routes.go)
enables its generic thinking-output parser only when thinking is requested. This
is consistent with the observed reasoning-like text and closing tag in ordinary
content under `think=false`; it is not evidence that the SDK omitted the flag.

Increasing the budget to 1,024 did not fix the first response in this test. This
does not prove that no larger budget could ever work. A properly configured
thinking-model experiment would instead need a separate, justified output budget,
reasoning-field handling and sampling policy. That is a different baseline from
the small non-thinking agent intended here.

## Recommendation at diagnosis — subsequently approved

Test `qwen3:4b-instruct-2507-q4_K_M` as the replacement baseline. Its
[official model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) documents
non-thinking behavior, and its [Ollama listing](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M)
shows approximately 2.5 GB and digest prefix `0edcdef34593`. This is a candidate,
not a tested fix or proof it will obey our JSON/tool contracts.

If approved: retain the current model and all old artifacts; download only that
explicit tag; verify its installed checkpoint metadata and full digest; test
no-fault baseline and read-back runs with the existing 512-token budget and strict
grader before a bounded new comparison. Keep any unfavorable outcomes. Add a
checkpoint-identity/preflight regression when implementing that model selection.

No download, model substitution, daemon change, default-budget change, parser
relaxation, application source change, new 20-trial batch, commit, push, or M05
advancement was performed during this diagnosis.

## Local evidence

`runs/m04-output-probe-F7etjA/` contains the original metadata and mistaken debug
response. `corrected/` contains the three planned request/response/render triples.
`probe.py` records the corrected diagnostic procedure and exclusively creates its
output directory; rerunning it in place refuses existing evidence.

These local artifacts are ignored by Git. The original 20-trial comparison remains
unchanged and inconclusive; this note explains its setup limitation, not a new
safeguard-success claim.
