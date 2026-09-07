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
        requirements = work / "requirements.txt"
        run(
            [
                "uv",
                "export",
                "--frozen",
                "--offline",
                "--no-dev",
                "--no-emit-project",
                "--format",
                "requirements.txt",
                "--output-file",
                str(requirements),
                "--quiet",
            ],
            cwd=root,
            env=env,
        )
        venv = work / "venv"
        run(
            ["uv", "venv", "--offline", "--python", sys.executable, str(venv)],
            cwd=work,
            env=env,
        )
        python = venv / "bin" / "python"
        run(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--require-hashes",
                "--python",
                str(python),
                "-r",
                str(requirements),
            ],
            cwd=work,
            env=env,
        )
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
    from importlib.metadata import version as installed_version
    from unittest.mock import patch

    import agent_fault_lab
    from agent_fault_lab.cli import main

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
    print(f"PASS: installed wheel {version}; scripted runs, comparison and reports")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--installed":
        check_installed(sys.argv[2])
    elif len(sys.argv) == 1:
        check_distribution()
    else:
        raise SystemExit("Usage: python scripts/check_distribution.py")
