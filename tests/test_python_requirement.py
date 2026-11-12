"""PyNIDM 5.0.0, which requirements.txt pins, requires Python 3.10 or newer.

Declaring an older floor makes `pip install` on 3.9 fail in dependency
resolution with a message about pynidm instead of the app's own Python
requirement.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_setup_py_requires_python_3_10():
    text = (ROOT / "setup.py").read_text()
    assert re.findall(r'python_requires="([^"]+)"', text) == [">=3.10"]
    versions = re.findall(r"Programming Language :: Python :: (3\.\d+)", text)
    assert versions and all(int(v.split(".")[1]) >= 10 for v in versions), versions


def test_setup_cfg_requires_python_3_10():
    text = (ROOT / "setup.cfg").read_text()
    assert re.findall(r"^python_requires\s*=\s*(\S+)$", text, re.MULTILINE) == [">=3.10"]
    versions = re.findall(r"Programming Language :: Python :: (3\.\d+)", text)
    assert all(int(v.split(".")[1]) >= 10 for v in versions), versions


def _setup_python_versions(workflow):
    """Every Python version each actions/setup-python step of a workflow
    installs, with ${{ matrix.<key> }} resolved from the job's matrix
    (values and include entries). An expression it cannot resolve, or a step
    without python-version, is returned as is and fails the version check."""
    found = []
    for job in (yaml.safe_load(workflow.read_text()).get("jobs") or {}).values():
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        for step in job.get("steps") or []:
            if not str(step.get("uses", "")).startswith("actions/setup-python"):
                continue
            value = (step.get("with") or {}).get("python-version")
            values = value if isinstance(value, list) else [value]
            for v in values:
                m = re.fullmatch(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", str(v).strip())
                if not m:
                    found.append(v)
                    continue
                key = m.group(1)
                listed = matrix.get(key)
                resolved = (listed if isinstance(listed, list) else [listed] if listed else [])
                resolved += [inc[key] for inc in matrix.get("include") or [] if key in inc]
                found.extend(resolved or [v])
    return found


def _is_3_10_or_newer(version):
    # A float means an unquoted YAML version: 3.10 reads as 3.1.
    m = re.fullmatch(r"3\.(\d+)(\.\d+)?", version) if isinstance(version, str) else None
    return bool(m) and int(m.group(1)) >= 10


def test_ci_runs_python_3_10_or_newer():
    """Every Python CI sets up is 3.10 or newer, whether a step names it or
    a matrix does, and at least one workflow sets one up."""
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    versions = {w.name: _setup_python_versions(w) for w in workflows}
    assert any(versions.values()), f"no actions/setup-python version in {versions}"
    for name, found in versions.items():
        assert all(_is_3_10_or_newer(v) for v in found), (name, found)
