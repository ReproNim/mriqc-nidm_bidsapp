"""Make the tests that run the real csv2nidm run wherever PyNIDM is installed.

The app starts csv2nidm from PATH. When pytest is started with a virtual
environment's interpreter whose bin directory is not on PATH, csv2nidm sits
next to that interpreter but is not found, and every csv2nidm test would
skip. The interpreter's directory is put on PATH first.

Under CI (the CI environment variable, which GitHub Actions sets), a missing
csv2nidm stops the run instead of skipping those tests, so a PyNIDM change
cannot pass CI untested.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

_bin = Path(sys.executable).parent
if shutil.which("csv2nidm") is None and (_bin / "csv2nidm").exists():
    os.environ["PATH"] = os.pathsep.join([str(_bin), os.environ.get("PATH", "")])


def pytest_configure(config):
    if os.environ.get("CI") and shutil.which("csv2nidm") is None:
        raise pytest.UsageError(
            "csv2nidm (PyNIDM) is not installed, so the csv2nidm tests would "
            "skip; install requirements.txt"
        )
