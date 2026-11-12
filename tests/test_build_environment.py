"""The images must not put the working directory on sys.path.

Python reads an empty PYTHONPATH entry as the working directory and places it
ahead of the standard library and site-packages, for the app, for the csv2nidm
it starts and for MRIQC. The base image sets no PYTHONPATH and BABS passes
none, so `/opt:$PYTHONPATH` is `/opt:`: a `nidm`, `pandas` or `json.py` in the
job's working directory then replaces the installed one, and on Python 3.11
(the image's) no interpreter can start once that directory has been removed.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()
SINGULARITY = (ROOT / "Singularity").read_text()


def _commands(text):
    """Non-blank, non-comment lines, stripped."""
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _singularity_section(name):
    head = re.search(rf"^%{name}\s*$", SINGULARITY, re.MULTILINE)
    assert head, f"Singularity has no %{name} section"
    rest = SINGULARITY[head.end():]
    nxt = re.search(r"^%\w+\s*$", rest, re.MULTILINE)
    return _commands(rest[: nxt.start()] if nxt else rest)


def _pythonpath_after(assignment, host_value):
    """PYTHONPATH after `assignment` runs in sh, from host_value (None = unset)."""
    prelude = "unset PYTHONPATH" if host_value is None else f"export PYTHONPATH='{host_value}'"
    out = subprocess.run(["sh", "-c", f'{prelude}; {assignment}; printf %s "$PYTHONPATH"'],
                         capture_output=True, text=True, check=True)
    return out.stdout


@pytest.mark.parametrize("host_value", [None, "", "/host/lib"])
def test_singularity_pythonpath_never_adds_the_working_directory(host_value):
    lines = [c for c in _singularity_section("environment") if "PYTHONPATH" in c]
    assert lines == ["export PYTHONPATH=/opt${PYTHONPATH:+:$PYTHONPATH}"], lines
    entries = _pythonpath_after(lines[0], host_value).split(":")
    assert "" not in entries, entries
    assert entries[0] == "/opt"
    if host_value:
        assert entries[1:] == [host_value]


@pytest.mark.parametrize("assignment", [
    "export PYTHONPATH=/opt:$PYTHONPATH", "export PYTHONPATH=$PYTHONPATH:/opt"])
def test_pythonpath_check_sees_an_empty_entry(assignment):
    """Positive control: the old form leaves an empty entry with no host value."""
    assert "" in _pythonpath_after(assignment, None).split(":")


def test_dockerfile_pythonpath_is_only_opt():
    """The base image sets no PYTHONPATH, so `/opt:$PYTHONPATH` would end in an
    empty entry. Nothing else is added: a Docker build sees no host value."""
    env = [c for c in _commands(DOCKERFILE) if re.match(r"ENV\s+PYTHONPATH\b", c)]
    assert env == ["ENV PYTHONPATH=/opt"], env
