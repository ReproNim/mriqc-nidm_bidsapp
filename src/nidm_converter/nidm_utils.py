"""
Utility functions for NIDM operations.

This module provides helper functions for NIDM file handling, path construction,
and label normalization used across the NIDM conversion pipeline.
"""

from pathlib import Path
from typing import Optional


def get_nidm_data_file(filename: str) -> Path:
    """
    Get path to a NIDM data file.

    Args:
        filename: Name of the data file (e.g., "mriqc_dictionary_v1.csv")

    Returns:
        Path to the data file

    Raises:
        FileNotFoundError: If the file doesn't exist

    Examples:
        >>> from nidm_converter.nidm_utils import get_nidm_data_file
        >>> dict_path = get_nidm_data_file("mriqc_dictionary_v1.csv")
        >>> dict_path.exists()
        True
    """
    from .data import get_data_file
    return get_data_file(filename)


def normalize_subject_label(label: str) -> str:
    """
    Normalize subject label by removing 'sub-' prefix if present.

    Args:
        label: Subject label (with or without 'sub-' prefix)

    Returns:
        Subject label without prefix

    Examples:
        >>> normalize_subject_label("sub-01")
        '01'
        >>> normalize_subject_label("01")
        '01'
        >>> normalize_subject_label("sub-0051456")
        '0051456'
    """
    if label.startswith("sub-"):
        return label[4:]  # Remove 'sub-' prefix
    return label


def normalize_session_label(label: Optional[str]) -> Optional[str]:
    """
    Normalize session label by removing 'ses-' prefix if present.

    Args:
        label: Session label (with or without 'ses-' prefix), or None

    Returns:
        Session label without prefix, or None if input was None

    Examples:
        >>> normalize_session_label("ses-baseline")
        'baseline'
        >>> normalize_session_label("baseline")
        'baseline'
        >>> normalize_session_label(None)
        None
    """
    if label is None:
        return None
    if label.startswith("ses-"):
        return label[4:]  # Remove 'ses-' prefix
    return label


def build_nidm_output_path(
    base_nidm_dir: Path,
    subject_id: str,
    session_id: Optional[str] = None
) -> Path:
    """
    Build NIDM output directory path with subject/session subdirectories.

    Creates path following BIDS derivatives structure:
    - Without session: base_nidm_dir/sub-{subject_id}/
    - With session: base_nidm_dir/sub-{subject_id}/ses-{session_id}/

    Args:
        base_nidm_dir: Base NIDM output directory
        subject_id: Subject ID (without 'sub-' prefix)
        session_id: Session ID (without 'ses-' prefix), optional

    Returns:
        Path to subject/session-specific NIDM directory

    Examples:
        >>> from pathlib import Path
        >>> base = Path("/output/mriqc-nidm_bidsapp/nidm")
        >>> build_nidm_output_path(base, "01")
        PosixPath('/output/mriqc-nidm_bidsapp/nidm/sub-01')
        >>> build_nidm_output_path(base, "01", "baseline")
        PosixPath('/output/mriqc-nidm_bidsapp/nidm/sub-01/ses-baseline')
    """
    # Normalize labels (remove prefixes if present)
    subject_id = normalize_subject_label(subject_id)
    session_id = normalize_session_label(session_id)

    # Build path with subdirectories
    subject_dir = base_nidm_dir / f"sub-{subject_id}"

    if session_id:
        return subject_dir / f"ses-{session_id}"
    else:
        return subject_dir


def build_nidm_filename(subject_id: str, session_id: Optional[str] = None) -> str:
    """
    Build NIDM TTL filename following BIDS naming convention.

    Args:
        subject_id: Subject ID (without 'sub-' prefix)
        session_id: Session ID (without 'ses-' prefix), optional

    Returns:
        NIDM filename (e.g., "sub-01.ttl" or "sub-01_ses-baseline.ttl")

    Examples:
        >>> build_nidm_filename("01")
        'sub-01.ttl'
        >>> build_nidm_filename("01", "baseline")
        'sub-01_ses-baseline.ttl'
    """
    # Normalize labels
    subject_id = normalize_subject_label(subject_id)
    session_id = normalize_session_label(session_id)

    filename = f"sub-{subject_id}"
    if session_id:
        filename += f"_ses-{session_id}"
    filename += ".ttl"

    return filename


__all__ = [
    "get_nidm_data_file",
    "normalize_subject_label",
    "normalize_session_label",
    "build_nidm_output_path",
    "build_nidm_filename",
]
