"""MRIQC-NIDM BIDSAPP - Run MRIQC and convert outputs to NIDM format."""
import json
from pathlib import Path


def get_version():
    """Read version from VERSION file"""
    # If installed as a package, VERSION should be in the root of the package
    # or one level up from this file's directory if in src structure
    # A missing or unreadable VERSION reports "unknown", never a plausible
    # version number: the value lands in dataset_description.json and the
    # MRIQC provenance, where a wrong number looks exactly like a right one.
    version_file = Path(__file__).parent.parent / "VERSION"
    try:
        with open(version_file) as f:
            data = json.load(f)
            return data["mriqc-nidm"]["version"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return "unknown"


__version__ = get_version()
__author__ = "ReproNim"
__license__ = "MIT"
