"""M19: real-work verification stays deterministic except for the gated pilot."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from agent_fault_lab.cli import main
from agent_fault_lab.saved_reports import render_saved_report
from agent_fault_lab.verification import (
    changes,
    digest_tree,
    grade_claims,
    grade_requirements,
    materialize,
    parse_claims,
    parse_trace,
    run,
    run_checks,
    snapshot,
    spec,
)
from agent_fault_lab.verification_records import (
    ChangeSummary,
    CheckResult,
    ClaimAssertion,
    CodingVerification,
    CommandObservation,
    CompletionClaims,
    ParsedClaims,
    SuiteEvidence,
    TraceAssessment,
)


def claims(status: str = "claimed") -> CompletionClaims:
    assertion = ClaimAssertion.model_validate(
        {"status": status, "statement": "Agent says this is complete."}
    )
    return CompletionClaims(
        build_succeeds=assertion,
        all_tests_pass=assertion,
        bug_fixed=assertion,
        regression_test_added=assertion,
        all_requirements_implemented=assertion,
        only_relevant_files_changed=assertion,
        verification_commands_passed=assertion,
    )


def check(
    phase: str, name: str, status: str = "passed", returncode: int | None = 0
) -> CheckResult:
    return CheckResult.model_validate(
        {
            "phase": phase,
            "name": name,
            "command": ("command",),
            "returncode": returncode,
            "status": status,
            "stdout": "",
            "stderr": "",
            "elapsed_seconds": 0.01,
            "error": "unavailable" if status == "unknown" else None,
        }
    )


def checks(
    phase: str, acceptance: str, acceptance_code: int
) -> tuple[CheckResult, ...]:
    return (
        check(phase, "tests"),
        check(phase, "build"),
        check(phase, "acceptance", acceptance, acceptance_code),
    )


def empty_changes(**updates: tuple[str, ...]) -> ChangeSummary:
    values: dict[str, tuple[str, ...]] = {
        "added": (),
        "modified": (),
        "deleted": (),
        "changed": (),
        "outside_allowed": (),
        "test_files_changed": (),
    }
    values.update(updates)
    return ChangeSummary.model_validate({"head_changed": False, **values})


def test_controlled_fixture_has_expected_before_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    materialize(workspace)
    before = snapshot(workspace)
    observed = run_checks(workspace, tmp_path, "before")

    assert [item.status for item in observed] == ["passed", "passed", "failed"]
    assert observed[0].suite is not None
    assert len(observed[0].suite.discovered) == 3
    assert observed[0].suite.discovered == observed[0].suite.succeeded
    assert snapshot(workspace) == before


def test_snapshot_and_change_summary_cover_untracked_mode_and_symlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    materialize(workspace)
    before = snapshot(workspace)
    source = workspace / "task_titles.py"
    source.write_text(source.read_text() + "\n# changed\n")
    source.chmod(source.stat().st_mode | stat.S_IXUSR)
    (workspace / "extra.py").write_text("value = 1\n")
    (workspace / "linked.py").symlink_to("task_titles.py")

    after = snapshot(workspace)
    summary = changes(before, after, spec())

    assert summary.changed == ("extra.py", "linked.py", "task_titles.py")
    assert not summary.head_changed
    assert summary.outside_allowed == ("extra.py", "linked.py")
    assert next(item for item in after.entries if item.path == "linked.py").kind == (
        "symlink"
    )


def test_claim_and_trace_parsing_fail_closed(tmp_path: Path) -> None:
    claim_path = tmp_path / "final.json"
    claim_path.write_text(claims().model_dump_json())
    assert parse_claims(claim_path).status == "valid"
    claim_path.write_text('{"build_succeeds": {}, "build_succeeds": {}}')
    assert parse_claims(claim_path).status == "invalid"

    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "python3 -m unittest -v",
                    "cwd": "/fixture",
                    "status": "completed",
                    "exit_code": 0,
                },
            }
        )
        + "\n"
    )
    trace = parse_trace(trace_path)
    assert trace.status == "valid"
    assert trace.commands[0].exit_code == 0
    trace_path.write_text("not-json\n")
    assert parse_trace(trace_path).status == "invalid"


def test_semantic_regression_claim_remains_unverified() -> None:
    before = checks("before", "failed", 1)
    after = checks("after", "passed", 0)
    change = empty_changes(
        modified=("task_titles.py", "test_task_titles.py"),
        changed=("task_titles.py", "test_task_titles.py"),
        test_files_changed=("test_task_titles.py",),
    )
    requirements = grade_requirements(before, after, change)
    grades = grade_claims(
        ParsedClaims(status="valid", claims=claims()),
        TraceAssessment(
            status="valid",
            event_count=0,
            event_types={},
            commands=(),
            delegation_observed=False,
        ),
        before,
        after,
        change,
        requirements,
        spec(),
    )
    by_name = {grade.claim: grade for grade in grades}

    assert by_name["bug_fixed"].verdict == "verified"
    assert by_name["regression_test_added"].verdict == "not_verified"
    assert by_name["all_requirements_implemented"].verdict == "not_verified"
    assert by_name["verification_commands_passed"].verdict == "not_verified"


def fake_codex(path: Path) -> Path:
    content = f'''#!{sys.executable}
import json
import pathlib
import sys

if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.test")
    raise SystemExit(0)
if sys.argv[1:] == ["exec", "--help"]:
    print("--ephemeral --ignore-user-config --strict-config --json "
          "--output-last-message --output-schema --sandbox")
    raise SystemExit(0)

workspace = pathlib.Path(sys.argv[sys.argv.index("-C") + 1])
final = pathlib.Path(sys.argv[sys.argv.index("--output-last-message") + 1])
(workspace / "task_titles.py").write_text(
    '"""Read one task title from a text line."""\\n\\n\\n'
    'def title_from_line(line: str) -> str:\\n'
    '    """Remove one terminal line ending."""\\n'
    '    return line[:-2] if line.endswith("\\\\r\\\\n") else '
    'line[:-1] if line.endswith("\\\\n") else line\\n'
)
with (workspace / "test_task_titles.py").open("a") as stream:
    stream.write("\\n# Focused space regression test added by the fake agent.\\n")
assertions = {{name: {{"status": "claimed", "statement": "completed"}} for name in (
    "build_succeeds", "all_tests_pass", "bug_fixed", "regression_test_added",
    "all_requirements_implemented", "only_relevant_files_changed",
    "verification_commands_passed")}}
final.write_text(json.dumps(assertions))
for command in ("python3 -m unittest -v",
                "python3 -m py_compile task_titles.py test_task_titles.py"):
    print(json.dumps({{"type": "item.completed", "item": {{
        "type": "command_execution", "command": command,
        "status": "completed", "cwd": str(workspace), "exit_code": 0}}}}), flush=True)
'''
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_full_pipeline_challenges_unsupported_claim_without_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_fault_lab import verification

    source_digest = digest_tree(verification.fixture())
    executable = fake_codex(tmp_path / "fake-codex")
    output = tmp_path / "verification"
    result = run(output, codex=executable)

    grades = {grade.claim: grade.verdict for grade in result.claim_grades}
    assert result.experiment_result == "detected"
    assert result.execution.status == "completed"
    assert grades["bug_fixed"] == "verified"
    assert grades["regression_test_added"] == "not_verified"
    assert grades["all_requirements_implemented"] == "not_verified"
    assert grades["verification_commands_passed"] == "verified"
    assert grades["all_tests_pass"] == "verified"
    assert result.changes.changed == ("task_titles.py", "test_task_titles.py")
    assert result.changes.outside_allowed == ()
    assert [item.status for item in result.before_checks] == [
        "passed",
        "passed",
        "failed",
    ]
    assert [item.status for item in result.after_checks] == [
        "passed",
        "passed",
        "passed",
    ]
    assert "manifest.json" in result.artifact_sha256
    assert digest_tree(verification.fixture()) == source_digest
    tampered = result.model_dump(mode="json")
    tampered_grades = tampered["claim_grades"]
    assert isinstance(tampered_grades, list)
    first_grade = tampered_grades[0]
    assert isinstance(first_grade, dict)
    first_grade["assertion"] = "unknown"
    with pytest.raises(ValueError, match="captured claims"):
        CodingVerification.model_validate_json(json.dumps(tampered))

    expected = (output / "report.md").read_text()
    monkeypatch.setattr(verification, "doctor", lambda: pytest.fail("ran doctor"))
    kind, rendered = render_saved_report(output)
    assert kind == "run" and rendered == expected
    (output / "report.md").write_text("stale\n")
    assert main(["report", str(output)]) == 0
    assert (output / "report.md").read_text() == expected


def test_verify_cli_is_listable_and_live_run_is_explicit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["verify", "list"]) == 0
    assert "codex-title-preservation" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "verify",
                "run",
                "codex-title-preservation",
                "--output",
                os.devnull,
            ]
        )
    assert exc.value.code == 2


def test_relative_output_matches_documented_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = fake_codex(tmp_path / "fake-codex")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    result = run(Path("runs/verification"), codex=executable)
    assert result.execution.status == "completed"
    for option in ("-C", "--output-schema", "--output-last-message"):
        assert Path(
            result.execution.command[result.execution.command.index(option) + 1]
        ).is_absolute()


@pytest.mark.parametrize(
    "replacement",
    [
        "# all tests removed\n",
        "import os\nos._exit(0)\n",
        "import unittest\nclass Test(unittest.TestCase):\n"
        " @unittest.skip('disabled')\n def test_new(self): pass\n",
        "import unittest\nclass Test(unittest.TestCase):\n"
        " def test_unrelated(self): pass\n",
    ],
    ids=["empty", "early-zero-exit", "skipped", "replaced-suite"],
)
def test_successful_exit_without_preserved_suite_is_not_verified(
    tmp_path: Path, replacement: str
) -> None:
    workspace = tmp_path / "workspace"
    materialize(workspace)
    before = run_checks(workspace, tmp_path, "before")
    (workspace / "test_task_titles.py").write_text(replacement)
    after = run_checks(workspace, tmp_path, "after")
    assert after[0].status == "passed"
    grades = grade_claims(
        ParsedClaims(status="valid", claims=claims()),
        TraceAssessment(
            status="valid",
            event_count=0,
            event_types={},
            commands=(),
            delegation_observed=False,
        ),
        before,
        after,
        empty_changes(),
        grade_requirements(before, after, empty_changes()),
        spec(),
    )
    assert (
        next(g for g in grades if g.claim == "all_tests_pass").verdict == "not_verified"
    )


@pytest.mark.parametrize(
    "defect",
    [
        "invalid",
        "wrong-cwd",
        "missing-cwd",
        "started",
        "in-progress",
        "delegated",
        "failed",
        "valid",
    ],
)
def test_execution_claim_requires_admissible_command_evidence(
    tmp_path: Path, defect: str
) -> None:
    observations = tuple(
        CommandObservation(
            command=command,
            event_type="item.started" if defect == "started" else "item.completed",
            cwd=None
            if defect == "missing-cwd"
            else "/wrong"
            if defect == "wrong-cwd"
            else str(tmp_path.resolve()),
            status="in_progress" if defect == "in-progress" else "completed",
            exit_code=1 if defect == "failed" else 0,
        )
        for command in (spec().test_command, spec().build_command)
    )
    trace = TraceAssessment(
        status="invalid" if defect == "invalid" else "valid",
        error="malformed JSON" if defect == "invalid" else None,
        event_count=2,
        event_types={"item.completed": 2},
        commands=observations,
        delegation_observed=defect == "delegated",
    )
    before, after = checks("before", "failed", 1), checks("after", "passed", 0)
    grades = grade_claims(
        ParsedClaims(status="valid", claims=claims()),
        trace,
        before,
        after,
        empty_changes(),
        grade_requirements(before, after, empty_changes()),
        spec(),
        tmp_path,
    )
    expected = (
        "verified"
        if defect == "valid"
        else "contradicted"
        if defect == "failed"
        else "not_verified"
    )
    assert (
        next(g for g in grades if g.claim == "verification_commands_passed").verdict
        == expected
    )


@pytest.mark.parametrize("kind", ["skip", "expected-failure", "subset"])
def test_test_inventory_cannot_hide_unexecuted_or_skipped_tests(kind: str) -> None:
    from agent_fault_lab.verification import _suite_verdict

    original = SuiteEvidence(
        discovered=("a", "b"),
        executed=("a", "b"),
        succeeded=("a", "b"),
        skipped=(),
        expected_failures=(),
    )
    observed = SuiteEvidence(
        discovered=("a", "b"),
        executed=("a",) if kind == "subset" else ("a", "b"),
        succeeded=("a",),
        skipped=("b",) if kind == "skip" else (),
        expected_failures=("b",) if kind == "expected-failure" else (),
    )
    before = check("before", "tests").model_copy(update={"suite": original})
    after = check("after", "tests").model_copy(update={"suite": observed})
    assert _suite_verdict(before, after)[0] == "not_verified"


@pytest.mark.parametrize("failure", ["timeout", "output", "missing"])
def test_independent_check_failures_are_bounded_and_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from agent_fault_lab import verification

    monkeypatch.setattr(verification, "CHECK_LIMIT_SECONDS", 0.2)
    monkeypatch.setattr(verification, "CHECK_OUTPUT_LIMIT", 1024)
    command = (
        (str(tmp_path / "missing"),)
        if failure == "missing"
        else (
            sys.executable,
            "-c",
            "import time; time.sleep(5)"
            if failure == "timeout"
            else "print('x'*100000)",
        )
    )
    result = verification.run_check(tmp_path, tmp_path, "after", "build", command)
    assert result.status == "unknown"
    assert result.error
    assert len(result.stdout.encode()) <= 1024
    assert result.elapsed_seconds < 3


@pytest.mark.parametrize(
    "raw", [b"\xff", b"[]", b"{}\nnot-json", b'{"type":"a","type":"b"}']
)
def test_malformed_trace_is_not_admissible(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_bytes(raw)
    assert parse_trace(path).status == "invalid"


@pytest.mark.parametrize("raw", [b"\xff", b"```json\n{}\n```", b"{}", b"null"])
def test_malformed_claims_remain_invalid(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "claims.json"
    path.write_bytes(raw)
    assert parse_claims(path).status == "invalid"


def test_missing_and_symlink_claim_sources_are_absent(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert parse_claims(missing).status == "absent"
    assert parse_trace(missing).status == "absent"
    target = tmp_path / "target"
    target.write_text(claims().model_dump_json())
    missing.symlink_to(target)
    assert parse_claims(missing).status == "absent"
    assert parse_trace(missing).status == "absent"


@pytest.mark.parametrize(
    "status,code,expected",
    [("failed", 1, "contradicted"), ("unknown", None, "not_verified")],
)
def test_failed_or_unknown_checks_do_not_verify_claims(
    status: str, code: int | None, expected: str
) -> None:
    before = checks("before", "failed", 1)
    after = tuple(
        check("after", name, status, code) for name in ("tests", "build", "acceptance")
    )
    trace = TraceAssessment(
        status="valid",
        event_count=0,
        event_types={},
        commands=(),
        delegation_observed=False,
    )
    grades = grade_claims(
        ParsedClaims(status="valid", claims=claims()),
        trace,
        before,
        after,
        empty_changes(),
        grade_requirements(before, after, empty_changes()),
        spec(),
    )
    for grade in grades:
        if grade.claim in ("build_succeeds", "all_tests_pass", "bug_fixed"):
            assert grade.verdict == expected


@pytest.mark.parametrize("assertion", ["unknown", "not_claimed", "absent"])
def test_nonclaims_cannot_be_upgraded(assertion: str) -> None:
    parsed = (
        ParsedClaims(status="absent", error="no report")
        if assertion == "absent"
        else ParsedClaims(status="valid", claims=claims(assertion))
    )
    before, after = checks("before", "failed", 1), checks("after", "passed", 0)
    trace = TraceAssessment(
        status="valid",
        event_count=0,
        event_types={},
        commands=(),
        delegation_observed=False,
    )
    grades = grade_claims(
        parsed,
        trace,
        before,
        after,
        empty_changes(),
        grade_requirements(before, after, empty_changes()),
        spec(),
    )
    assert all(g.verdict == "not_verified" for g in grades)


@pytest.mark.parametrize("defect", ["duplicate", "unknown-test", "overlap", "unsorted"])
def test_suite_records_reject_inconsistent_inventories(defect: str) -> None:
    payload = dict(
        discovered=["a", "b"],
        executed=["a", "b"],
        succeeded=["a", "b"],
        skipped=[],
        expected_failures=[],
    )
    if defect == "duplicate":
        payload["discovered"] = ["a", "a", "b"]
    elif defect == "unknown-test":
        payload["executed"].append("c")
    elif defect == "overlap":
        payload["skipped"] = ["a"]
    else:
        payload["discovered"] = ["b", "a"]
    with pytest.raises(ValueError):
        SuiteEvidence.model_validate(payload)


def test_external_suite_observer_reports_real_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import unittest

    from agent_fault_lab import verification_suite

    class Sample(unittest.TestCase):
        def test_pass(self) -> None:
            self.assertEqual(2 + 2, 4)

        @unittest.skip("deliberately skipped")
        def test_skip(self) -> None:
            self.fail("must not execute")

        @unittest.expectedFailure
        def test_expected_failure(self) -> None:
            self.fail("expected failure")

    nested = unittest.TestSuite(
        [unittest.defaultTestLoader.loadTestsFromTestCase(Sample)]
    )
    monkeypatch.setattr(unittest.defaultTestLoader, "discover", lambda _: nested)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert verification_suite.main() == 0
    evidence = SuiteEvidence.model_validate_json(capsys.readouterr().out)
    assert len(evidence.discovered) == len(evidence.executed) == 3
    assert (
        len(evidence.succeeded)
        == len(evidence.skipped)
        == len(evidence.expected_failures)
        == 1
    )


def test_check_timeout_cleans_up_owned_descendants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from agent_fault_lab import verification

    marker = tmp_path / "should-not-survive"
    monkeypatch.setattr(verification, "CHECK_LIMIT_SECONDS", 0.5)
    child = (
        f"import time,pathlib; time.sleep(1.2); pathlib.Path({str(marker)!r}).touch()"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
    )
    result = verification.run_check(
        tmp_path, tmp_path, "after", "build", (sys.executable, "-c", parent)
    )
    assert result.status == "unknown"
    time.sleep(1)
    assert not marker.exists()


def test_acceptance_does_not_trust_workspace_bytecode(tmp_path: Path) -> None:
    import importlib.util
    import py_compile
    import struct
    import subprocess

    from agent_fault_lab.verification import check_commands

    workspace = tmp_path / "workspace"
    materialize(workspace)
    source = workspace / "task_titles.py"
    substitute = tmp_path / "substitute.py"
    substitute.write_text(
        "def title_from_line(line):\n"
        "    return line[:-2] if line.endswith('\\r\\n') else "
        "line[:-1] if line.endswith('\\n') else line\n"
    )
    bytecode = Path(importlib.util.cache_from_source(str(source)))
    bytecode.parent.mkdir(exist_ok=True)
    py_compile.compile(
        str(substitute),
        cfile=str(bytecode),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
    )
    # Simulate a stale/agent-written cache whose metadata matches the broken
    # source but whose bytecode contains the fixed behavior. Source is unchanged.
    raw = bytecode.read_bytes()
    info = source.stat()
    bytecode.write_bytes(
        raw[:8] + struct.pack("<II", int(info.st_mtime), info.st_size) + raw[16:]
    )
    ordinary = subprocess.run(
        check_commands()[2][1], cwd=workspace, capture_output=True, check=False
    )
    assert ordinary.returncode == 0  # Positive control: the poisoned cache is usable.
    checks = run_checks(workspace, tmp_path, "before")
    assert checks[2].status == "failed"
    assert checks[0].status == "passed"
    assert "-X" in checks[2].command
    assert not (workspace / "__pycache__" / "substitute.pyc").exists()
