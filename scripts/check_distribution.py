"""Install the locked runtime and built wheel offline, then check the public CLI."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory


def run(args: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def check_distribution() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    wheel = root / "dist" / f"agent_fault_lab-{version}-py3-none-any.whl"
    if not wheel.is_file():
        raise FileNotFoundError(f"Build the wheel first: {wheel}")
    env = dict(os.environ)
    # Never allow the source tree or active uv environment to satisfy the import.
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        env.pop(key, None)
    env.update(AFLAB_RUN_LIVE_TESTS="0", AFLAB_LIVE_TEST_COMMAND="0")
    with TemporaryDirectory(prefix="aflab-wheel-") as temporary:
        work = Path(temporary)
        venv = work / "venv"
        # Sync directly from the lock: cached wheels alone do not provide the
        # index metadata needed to resolve an exported requirements file offline.
        run(
            [
                "uv",
                "sync",
                "--locked",
                "--offline",
                "--no-dev",
                "--no-install-project",
                "--python",
                sys.executable,
            ],
            cwd=root,
            env={**env, "UV_PROJECT_ENVIRONMENT": str(venv)},
        )
        python = venv / "bin" / "python"
        run(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(python),
                str(wheel),
            ],
            cwd=work,
            env=env,
        )
        run(
            [str(python), "-I", str(Path(__file__).resolve()), "--installed", version],
            cwd=work,
            env=env,
        )


def check_installed(version: str) -> None:
    import hashlib
    import json
    from contextlib import redirect_stdout
    from importlib.metadata import version as installed_version
    from io import StringIO
    from unittest.mock import patch

    import agent_fault_lab
    from agent_fault_lab.boundaries import load_boundary
    from agent_fault_lab.cli import main
    from agent_fault_lab.journal import atomic_json
    from agent_fault_lab.scanner import ScanResult

    def scripted_scan(content: bytes, directory: Path) -> ScanResult:
        directory.mkdir()
        (directory / "SKILL.md").write_bytes(content)
        result = ScanResult(
            engine="SCRIPTED installed-wheel scanner double, NOT SkillSpector",
            commit="test fixture",
            version="test fixture",
            input_sha256=hashlib.sha256(content).hexdigest(),
            status="admitted",
            recommendation="SAFE",
            complete=True,
            exit_code=0,
            elapsed_seconds=0,
        )
        atomic_json(directory / "scan.json", result.model_dump(mode="json"))
        return result

    location = Path(agent_fault_lab.__file__).resolve()
    assert location.is_relative_to(Path(sys.prefix).resolve()), location
    assert installed_version("agent-fault-lab") == version
    cli = Path(sys.executable).parent / "aflab"
    reported = subprocess.check_output([str(cli), "--version"], text=True).strip()
    assert reported == f"aflab {version}", reported

    work = Path.cwd()
    # Imports are complete. Exercise the installed entry point's implementation
    # with Python socket construction blocked, independently of pytest/plugins.
    with patch("socket.socket", side_effect=AssertionError("Network is forbidden")):
        for case in ("happy-path", "false-success", "invalid-report"):
            output = work / case
            assert (
                main(["demo", "--offline", "--case", case, "--output", str(output)])
                == 0
            )
            assert main(["report", str(output), "--check"]) == 0
        output = work / "comparison"
        assert (
            main(["compare", "--offline", "--trials", "1", "--output", str(output)])
            == 0
        )
        assert main(["report", str(output), "--check"]) == 0
        (output / "report.md").unlink()
        assert main(["report", str(output)]) == 0
        assert main(["report", str(output), "--check"]) == 0
        contracts = work / "contracts"
        assert (
            main(
                [
                    "reliability",
                    "compare",
                    "wrong-create-title",
                    "--offline",
                    "--output",
                    str(contracts),
                ]
            )
            == 0
        )
        assert main(["report", str(contracts), "--check"]) == 0
        for child in sorted(contracts.iterdir()):
            if child.is_dir():
                assert main(["report", str(child), "--check"]) == 0
        retries = work / "retries"
        assert (
            main(
                [
                    "reliability",
                    "compare",
                    "lost-reply-once",
                    "--offline",
                    "--include-control",
                    "--output",
                    str(retries),
                ]
            )
            == 0
        )
        assert main(["report", str(retries), "--check"]) == 0
        for child in sorted(retries.iterdir()):
            if child.is_dir():
                assert main(["report", str(child), "--check"]) == 0
        processes = work / "processes"
        assert (
            main(
                [
                    "reliability",
                    "compare",
                    "transient-once",
                    "--offline",
                    "--output",
                    str(processes),
                ]
            )
            == 0
        )
        assert main(["report", str(processes), "--check"]) == 0
        for child in sorted(processes.iterdir()):
            if child.is_dir():
                assert main(["resume", str(child), "--offline"]) == 0
                assert main(["report", str(child), "--check"]) == 0
                captured = StringIO()
                with redirect_stdout(captured):
                    assert main(["diagnose", str(child), "--format", "json"]) == 0
                assert json.loads(captured.getvalue())["gaps"] == []
        with patch(
            "agent_fault_lab.scanner.SkillSpector.scan", side_effect=scripted_scan
        ):
            boundary = work / "boundary"
            assert (
                main(
                    [
                        "boundaries",
                        "run",
                        "manual",
                        "--offline",
                        "--output",
                        str(boundary),
                    ]
                )
                == 3
            )
            operation = load_boundary(boundary).state.operation_id
            assert operation
            assert main(["approval", "approve", str(boundary), operation]) == 0
            assert main(["resume", str(boundary), "--offline"]) == 0
            assert main(["report", str(boundary), "--check"]) == 0
            captured = StringIO()
            with redirect_stdout(captured):
                assert main(["diagnose", str(boundary), "--format", "json"]) == 0
            assert json.loads(captured.getvalue())["gaps"] == []
            for case in ("injection-override", "memory-stale-title"):
                context = work / case
                assert (
                    main(
                        [
                            "boundaries",
                            "compare",
                            case,
                            "--offline",
                            "--output",
                            str(context),
                        ]
                    )
                    == 0
                )
                assert main(["report", str(context), "--check"]) == 0
                evidence = json.loads((context / "comparison.json").read_text())
                assert len(evidence["entries"]) == (
                    4 if case.startswith("injection-") else 2
                )
        study_plan = Path("study-plan.json")
        study_output = Path("study-output")
        assert (
            main(
                [
                    "study",
                    "plan",
                    "claims",
                    "--repetitions",
                    "1",
                    "--output",
                    str(study_plan),
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "study",
                    "run",
                    str(study_plan),
                    "--offline",
                    "--output",
                    str(study_output),
                ]
            )
            == 0
        )
        assert main(["study", "resume", str(study_output), "--offline"]) == 0
        assert main(["report", str(study_output), "--check"]) == 0
    audit = Path("wheel-evaluator-audit")
    with redirect_stdout(StringIO()):
        assert main(["evaluator", "audit", "--output", str(audit)]) == 0
        assert main(["report", str(audit), "--check"]) == 0
        assert main(["runtime", "doctor", "langgraph"]) == 2
        assert main(["external", "list"]) == 0
        assert main(["external", "doctor", "langgraph-router-resume"]) == 2
        # Explicitly synthetic unstarted inventory: checks the installed reader,
        # not external-framework behavior or the original report's finding.
        from agent_fault_lab.external import save as save_external
        from agent_fault_lab.external_records import (
            CONDITIONS,
            MODES,
            Identity,
            Reproduction,
            Slot,
        )

        external_report = work / "external-report"
        external_report.mkdir()
        save_external(
            external_report,
            Reproduction(
                identity=Identity(
                    python="3.12.0",
                    platform="synthetic installed-wheel reader check",
                    dependencies={
                        "langgraph": "1.2.11",
                        "langgraph-checkpoint-sqlite": "3.1.1",
                    },
                    source_sha256="0" * 64,
                    lock_sha256="1" * 64,
                    harness_sha256="2" * 64,
                ),
                created_at="synthetic fixture",
                status="unstarted",
                slots=tuple(
                    Slot(
                        id=f"{m}-{c}-{r}",
                        mode=m,
                        condition=c,
                        repetition=r,
                        thread_id=f"{m}-{c}-{r}",
                    )
                    for m in MODES
                    for c in CONDITIONS
                    for r in range(1, 4)
                ),
            ),
        )
        assert main(["report", str(external_report), "--check"]) == 0
    print(
        f"PASS: installed wheel {version}; runs, studies, evaluator audit and reports"
    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--installed":
        check_installed(sys.argv[2])
    elif len(sys.argv) == 1:
        check_distribution()
    else:
        raise SystemExit("Usage: python scripts/check_distribution.py")
