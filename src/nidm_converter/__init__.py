"""
NIDM (Neuroimaging Data Model) conversion package.

This package provides tools for converting MRIQC quality control metrics
to NIDM format for improved interoperability and integration with existing
neuroimaging analysis provenance graphs.

Modules:
    nidm_converter: NIDM file detection, copying, and preparation
    json_to_csv: Convert MRIQC JSON outputs to CSV format
    csv_to_nidm: Convert CSV files to NIDM TTL format
    nidm_utils: Utility functions for NIDM operations
    data: NIDM data files (dictionaries, software metadata)
"""

from .nidm_converter import (
    detect_existing_nidm,
    copy_and_prepare_nidm,
)
from .json_to_csv import convert_mriqc_json_to_csv
from .csv_to_nidm import convert_csv_to_nidm
from .nidm_utils import (
    build_nidm_output_path,
    build_nidm_filename,
    normalize_subject_label,
    normalize_session_label,
)

__version__ = "0.1.0"

__all__ = [
    "detect_existing_nidm",
    "copy_and_prepare_nidm",
    "convert_mriqc_json_to_csv",
    "convert_csv_to_nidm",
    "build_nidm_output_path",
    "build_nidm_filename",
    "normalize_subject_label",
    "normalize_session_label",
]
