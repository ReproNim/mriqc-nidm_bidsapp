"""Every command in Singularity's %post must be able to fail the build.

`set -e` does not apply to a command of an `&&` list other than the last, so
`micromamba install ... && pip install -r requirements.txt && pip install -e .`
went on after a failing micromamba or `pip install -r`, skipped the app's own
install, and %post still exited 0: a SIF without PyNIDM 5.0.0 and without the
`mriqc-nidm` console script that %runscript starts.

The test runs the recipe's own %post under sh, with PATH holding only stubs
for the external commands it calls. Each stub logs its call; the stub whose
call number is FAIL_AT exits 1. For every call in turn, %post must exit
non-zero at that call and run nothing after it. A new external command in
%post has no stub, so the run without failures fails until a stub is added.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SINGULARITY = (ROOT / "Singularity").read_text()

# External commands %post calls (everything else is a shell builtin).
STUBBED = ("apt-get", "micromamba", "pip", "mkdir", "chmod", "rm", "find")

STUB = """#!/bin/sh
read n < "$STUB_COUNTER"
n=$((n + 1))
echo "$n" > "$STUB_COUNTER"
echo "{name} $*" >> "$STUB_CALLS"
if [ "$n" = "$FAIL_AT" ]; then
    exit 1
fi
exit 0
"""

# Install steps the harness must reach, or it proves nothing about them.
INSTALLS = (
    "apt-get update",
    "apt-get install -y git build-essential",
    "micromamba install -n base -y -c conda-forge pandas click pybids",
    "pip install --no-cache-dir -r requirements.txt",
    "pip install --no-deps -e .",
)


def _post_body():
    head = re.search(r"^%post\s*$", SINGULARITY, re.MULTILINE)
    assert head, "Singularity has no %post section"
    rest = SINGULARITY[head.end():]
    nxt = re.search(r"^%\w+\s*$", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _shells():
    """/bin/sh (what Apptainer runs %post with), plus dash and bash if present:
    the image's /bin/sh is dash, a CI runner's too, this cluster's is bash."""
    found = {}
    for name in ("/bin/sh", "dash", "bash"):
        path = shutil.which(name)
        if path and os.path.realpath(path) not in found.values():
            found[name] = os.path.realpath(path)
    return sorted(found.values())


@pytest.fixture
def post(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in STUBBED:
        stub = stubs / name
        stub.write_text(STUB.format(name=name))
        stub.chmod(0o755)
    opt = tmp_path / "opt"
    opt.mkdir()
    script = tmp_path / "post.sh"
    script.write_text(_post_body().replace("/opt", str(opt)))

    def run(shell, fail_at):
        counter, calls = tmp_path / "counter", tmp_path / "calls"
        counter.write_text("0\n")
        calls.write_text("")
        env = {
            "PATH": str(stubs),
            "STUB_COUNTER": str(counter),
            "STUB_CALLS": str(calls),
            "FAIL_AT": str(fail_at),
            "APPTAINER_LABELS": str(tmp_path / "labels"),
        }
        # Without -e: the recipe's own `set -e` has to stop it.
        result = subprocess.run([shell, str(script)], env=env, cwd=tmp_path,
                                capture_output=True, text=True, timeout=60)
        return result, calls.read_text().splitlines()

    return run


@pytest.mark.parametrize("shell", _shells())
def test_post_runs_every_install_without_failures(post, shell):
    result, calls = post(shell, fail_at=0)
    assert result.returncode == 0, (result.returncode, result.stderr)
    for install in INSTALLS:
        assert any(c.startswith(install) for c in calls), (install, calls)


@pytest.mark.parametrize("shell", _shells())
def test_any_failing_command_fails_post(post, shell):
    _, calls = post(shell, fail_at=0)
    assert len(calls) >= len(INSTALLS), calls
    problems = []
    for k, call in enumerate(calls, start=1):
        result, ran = post(shell, fail_at=k)
        if result.returncode == 0:
            problems.append(f"%post exits 0 when `{call}` fails (call {k})")
        if len(ran) != k:
            problems.append(f"%post went on after `{call}` failed: {ran[k:]}")
    assert not problems, "\n".join(problems)
