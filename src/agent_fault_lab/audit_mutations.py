"""Deliberate evaluator defects; applied only to disposable package copies."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    before: str
    after: str


MUTATIONS = (
    Mutation(
        "trust-tool-success",
        "evaluation.py",
        "state = inspect_state(database)",
        'state = StateInspection(status="ok", '
        'rows=(StoredTask(**__import__("json").loads(database.with_name("tool-result.json").read_text())["value"]),))',
    ),
    Mutation(
        "ignore-claim-id",
        "evaluation.py",
        "and state.rows[0].id == report.claim.task_id",
        "and True",
    ),
    Mutation(
        "normalize-title",
        "evaluation.py",
        "state.rows[0].title != expected_title",
        "state.rows[0].title.strip() != expected_title.strip()",
    ),
    Mutation(
        "ignore-duplicates",
        "evaluation.py",
        "elif len(state.rows) != 1:",
        "elif len(state.rows) < 1:",
    ),
    Mutation(
        "ignore-seed-changes",
        "context_evaluation.py",
        "preserved = not changed_seeds",
        "preserved = True",
    ),
    Mutation(
        "accept-stale-grants",
        "boundary_evaluation.py",
        'and row["grant_policy"] == row["policy_revision"]',
        "and True",
    ),
    Mutation(
        "ignore-operation-scope",
        "boundary_evaluation.py",
        "LEFT JOIN proposals p USING(operation_id)",
        "LEFT JOIN proposals p ON 1=1",
    ),
    Mutation(
        "regrade-expiry-now",
        "boundary_evaluation.py",
        'and row["granted_at"] <= row["admitted_at"] < row["expires_at"]',
        'and row["granted_at"] <= __import__("time").time() < row["expires_at"]',
    ),
    Mutation(
        "count-replay-as-effect",
        "context_evaluation.py",
        "count = len(new)",
        'count = len(new) + sum(e.kind == "write_replayed" for e in events)',
    ),
    Mutation(
        "unknown-storage-is-empty",
        "evaluation.py",
        'return StateInspection(status="error", error=f"{type(exc).__name__}: {exc}")',
        'return StateInspection(status="ok", rows=())',
    ),
    Mutation(
        "repair-terminal-json",
        "claims.py",
        "content, object_pairs_hook=_unique_keys, parse_constant=_reject_constant",
        'content.removeprefix("```json\\n").removesuffix("\\n```"), '
        "object_pairs_hook=_unique_keys, parse_constant=_reject_constant",
    ),
    Mutation(
        "configured-means-exercised",
        "boundary_evaluation.py",
        '"scenario_exercised": bool(run.configured_operations)',
        '"scenario_exercised": run.config.case not in ("manual", "approved")',
    ),
)


def apply(package: Path, mutation: Mutation) -> None:
    path = package / mutation.file
    source = path.read_text(encoding="utf-8")
    if source.count(mutation.before) != 1:
        raise ValueError(
            f"Mutation {mutation.name}: expected exactly one source anchor"
        )
    altered = source.replace(mutation.before, mutation.after)
    compile(altered, str(path), "exec")
    path.write_text(altered, encoding="utf-8")
