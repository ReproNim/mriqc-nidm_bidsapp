"""The version in VERSION, the one the app reports and the image's %help agree.

src.get_version() feeds dataset_description.json and the MRIQC provenance
record; setup.py reads the same key for the package; the Singularity %help is
what `apptainer run-help` shows. A release that bumps only some of these ships
an image that disagrees with itself.
"""
import json
import re
from pathlib import Path

import src

ROOT = Path(__file__).resolve().parent.parent
VERSION = json.loads((ROOT / "VERSION").read_text())["mriqc-nidm"]["version"]


def test_app_reports_the_version_file():
    assert src.get_version() == VERSION
    assert src.__version__ == VERSION


def test_singularity_help_names_the_version_file():
    text = (ROOT / "Singularity").read_text()
    found = re.findall(r"^\s+(?:MRIQC-NIDM BIDS App|- MRIQC-NIDM:) (\S+)$", text, re.MULTILINE)
    assert len(found) == 2, f"expected two version lines in %help, found {found}"
    assert set(found) == {VERSION}, f"Singularity %help says {found}, VERSION says {VERSION}"


def test_missing_version_file_reports_unknown(monkeypatch, tmp_path):
    """Not a stale number: a fallback of "0.1.0" would be silently wrong after a bump."""
    fake_init = tmp_path / "src" / "__init__.py"
    fake_init.parent.mkdir()
    fake_init.write_text("")
    monkeypatch.setattr(src, "__file__", str(fake_init))
    assert src.get_version() == "unknown"
