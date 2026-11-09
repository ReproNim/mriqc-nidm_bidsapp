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
STUBBED = ("apt-get", "micromamba", "pip", "python", "mkdir", "chmod", "rm", "find")

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
    # The PyNIDM build check, after the installs (src/check_pynidm.py).
    "python OPT/src/check_pynidm.py",
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
    # /usr/local/bin is the directory %environment puts first on PATH at run
    # time; here a scratch directory, so a test can place a command there.
    local_bin = tmp_path / "usr-local-bin"
    local_bin.mkdir()
    script.write_text(
        _post_body().replace("/opt", str(opt)).replace("/usr/local/bin", str(local_bin)))

    def run(shell, fail_at, path_extra=None, python=None):
        """python: an interpreter `python` in %post runs instead of its stub."""
        counter, calls = tmp_path / "counter", tmp_path / "calls"
        if python is not None:
            (stubs / "python").write_text(f'#!/bin/sh\nexec {python} "$@"\n')
        counter.write_text("0\n")
        calls.write_text("")
        env = {
            "PATH": str(stubs) + (f":{path_extra}" if path_extra else ""),
            "STUB_COUNTER": str(counter),
            "STUB_CALLS": str(calls),
            "FAIL_AT": str(fail_at),
            "APPTAINER_LABELS": str(tmp_path / "labels"),
        }
        # Without -e: the recipe's own `set -e` has to stop it.
        result = subprocess.run([shell, str(script)], env=env, cwd=tmp_path,
                                capture_output=True, text=True, timeout=60)
        return result, [c.replace(str(opt), "OPT") for c in calls.read_text().splitlines()]

    run.opt = opt
    run.local_bin = local_bin
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


# --- The PyNIDM build check, run for real against fake environments ---------

PIN = re.search(r"^pynidm==(\S+)$", (ROOT / "requirements.txt").read_text(), re.MULTILINE)


def test_build_check_expects_the_pinned_pynidm():
    import src.check_pynidm as check

    assert PIN and check.PYNIDM_VERSION == PIN.group(1)


def _venv(path):
    """A bare venv of this interpreter; returns (python, site-packages)."""
    import sys
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(path)], check=True)
    python = path / "bin" / "python"
    site_dir = subprocess.run(
        [str(python), "-c", "import site; print(site.getsitepackages()[0])"],
        capture_output=True, text=True, check=True).stdout.strip()
    return python, Path(site_dir)


def _install_fake_pynidm(site_dir, version="5.0.0"):
    (site_dir / "nidm").mkdir()
    (site_dir / "nidm" / "__init__.py").write_text("")
    info = site_dir / f"pynidm-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: pynidm\nVersion: {version}\n")


@pytest.fixture
def image_env(tmp_path, post):
    """%post with `python` a venv holding a fake PyNIDM 5.0.0 and csv2nidm on
    PATH running that venv; the check script copied to <opt>/src. Each case
    breaks one thing before calling run()."""
    env = {"python": None}
    env["python"], env["site"] = _venv(tmp_path / "image")
    _install_fake_pynidm(env["site"])
    (post.opt / "src").mkdir()
    shutil.copy(ROOT / "src" / "check_pynidm.py", post.opt / "src" / "check_pynidm.py")
    bin_dir = tmp_path / "image-bin"
    bin_dir.mkdir()
    env["csv2nidm"] = bin_dir / "csv2nidm"

    def csv2nidm_running(python):
        env["csv2nidm"].write_text(f"#!{python}\nimport nidm\n")
        env["csv2nidm"].chmod(0o755)

    csv2nidm_running(env["python"])
    env["csv2nidm_running"] = csv2nidm_running
    env["run"] = lambda: post("/bin/sh", 0, path_extra=str(bin_dir), python=env["python"])
    env["tmp"] = tmp_path
    return env


def _check_stops_post(result, calls, reason):
    assert result.returncode != 0, result.stderr
    assert "PyNIDM build check failed" in result.stderr and reason in result.stderr, result.stderr
    # Nothing after the check ran: the readability check (find) is last.
    assert not any(c.startswith("find ") for c in calls), calls


def test_build_check_passes_on_the_image_pynidm(image_env):
    result, calls = image_env["run"]()
    assert result.returncode == 0, result.stderr
    assert "PyNIDM 5.0.0 from " in result.stdout
    assert any(c.startswith("find ") for c in calls)


def test_build_check_fails_on_another_pynidm_version(image_env):
    site_dir = image_env["site"]
    shutil.rmtree(site_dir / "pynidm-5.0.0.dist-info")
    shutil.rmtree(site_dir / "nidm")
    _install_fake_pynidm(site_dir, version="4.5.0")
    _check_stops_post(*image_env["run"](), "pynidm is 4.5.0, not 5.0.0")


def test_build_check_fails_without_pynidm(image_env):
    shutil.rmtree(image_env["site"] / "nidm")
    _check_stops_post(*image_env["run"](), "nidm does not import")


def test_build_check_fails_on_a_nidm_outside_site_packages(image_env, post):
    """A nidm package on PYTHONPATH (here /opt, as %post sets it) shadows the
    installed one."""
    (post.opt / "nidm").mkdir()
    (post.opt / "nidm" / "__init__.py").write_text("")
    _check_stops_post(*image_env["run"](), "outside site-packages")


def test_build_check_fails_when_csv2nidm_runs_another_environment(image_env):
    other, other_site = _venv(image_env["tmp"] / "other")
    _install_fake_pynidm(other_site)
    image_env["csv2nidm_running"](other)
    _check_stops_post(*image_env["run"](), "runs nidm from")


def test_build_check_fails_when_csv2nidm_cannot_import_nidm(image_env):
    other, _ = _venv(image_env["tmp"] / "other")
    image_env["csv2nidm_running"](other)
    _check_stops_post(*image_env["run"](), "cannot import nidm")


def test_build_check_examines_the_run_time_csv2nidm(image_env, post):
    """At run time %environment puts /usr/local/bin first on PATH. A csv2nidm
    there, running another environment, is what a job would start, so the
    check must examine it rather than the build PATH's."""
    other, other_site = _venv(image_env["tmp"] / "other")
    _install_fake_pynidm(other_site)
    shadow = post.local_bin / "csv2nidm"
    shadow.write_text(f"#!{other}\nimport nidm\n")
    shadow.chmod(0o755)
    _check_stops_post(*image_env["run"](), f"{shadow} runs nidm from")


def test_build_check_fails_without_csv2nidm(image_env):
    image_env["csv2nidm"].unlink()
    _check_stops_post(*image_env["run"](), "csv2nidm is not on PATH")


def _docker_check_command():
    joined = re.sub(r"\\\n\s*", " ", (ROOT / "Dockerfile").read_text())
    runs = [line.strip()[len("RUN "):] for line in joined.splitlines()
            if line.strip().startswith("RUN ") and "check_pynidm.py" in line]
    assert len(runs) == 1, runs
    return runs[0]


def test_dockerfile_runs_the_build_check_after_the_installs():
    text = re.sub(r"\\\n\s*", " ", (ROOT / "Dockerfile").read_text())
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("RUN ")]
    check = next(i for i, line in enumerate(lines) if "check_pynidm.py" in line)
    install = max(i for i, line in enumerate(lines) if "pip install" in line)
    assert check > install


@pytest.mark.parametrize("version, status", [("5.0.0", 0), ("4.5.0", 1)])
def test_dockerfile_build_check_fails_on_another_pynidm_version(image_env, post, version, status):
    """The Dockerfile's RUN, executed by sh as `docker build` does, against the
    same fake image environment."""
    if version != "5.0.0":
        shutil.rmtree(image_env["site"] / "pynidm-5.0.0.dist-info")
        shutil.rmtree(image_env["site"] / "nidm")
        _install_fake_pynidm(image_env["site"], version=version)
    stubs = post.opt.parent / "stubs"
    (stubs / "python").write_text(f'#!/bin/sh\nexec {image_env["python"]} "$@"\n')
    command = _docker_check_command().replace("/opt", str(post.opt))
    result = subprocess.run(
        ["/bin/sh", "-c", command], capture_output=True, text=True, timeout=60,
        env={"PATH": f"{stubs}:{image_env['csv2nidm'].parent}"})
    assert (result.returncode != 0) == bool(status), result.stderr


def test_singularity_check_uses_the_run_time_path():
    """%post runs with the base image's PATH; the check must be given the
    PATH %environment sets, which is what a job resolves python and csv2nidm
    with. (Docker's RUN already sees ENV PATH.)"""
    env = re.search(r"^%environment\s*$(.*?)^%\w+", SINGULARITY, re.MULTILINE | re.DOTALL)
    exports = re.findall(r"^\s*export PATH=(\S+)$", env.group(1), re.MULTILINE)
    assert len(exports) == 1, exports
    checks = [line.strip() for line in _post_body().splitlines() if "check_pynidm.py" in line
              and not line.strip().startswith("#")]
    assert len(checks) == 1, checks
    assert checks[0].startswith(f"PATH={exports[0]} "), (checks[0], exports[0])
