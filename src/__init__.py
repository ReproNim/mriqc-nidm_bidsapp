"""MRIQC-NIDM BIDSAPP - Run MRIQC and convert outputs to NIDM format."""
import json
from pathlib import Path

def get_version():
    """Read version from VERSION file"""
    # If installed as a package, VERSION should be in the root of the package
    # or one level up from this file's directory if in src structure
    version_file = Path(__file__).parent.parent / "VERSION"
    if not version_file.exists():
        # Fallback for installed package where VERSION might be elsewhere
        # or if we are in a different structure
        return "0.1.0"
    
    try:
        with open(version_file) as f:
            data = json.load(f)
            return data["mriqc_nidm_bidsapp"]["version"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return "0.1.0"

__version__ = get_version()
__author__ = "ReproNim"
__license__ = "MIT"
