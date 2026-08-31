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


def build_subject_output_path(
    output_dir: Path,
    subject_id: str,
    session_id: Optional[str] = None
) -> Path:
    """
    Build the per-subject output directory -- the unit BABS zips.

    Everything this app produces for a subject lives under that subject's own
    directory, with nidm.ttl beside the analysis results:

        <output_dir>/sub-{subject_id}[/ses-{session_id}]/

    There is no app-name wrapper directory and no shared nidm/ directory. This
    matches the study-wide layout adopted by the sibling freesurfer-nidm and
    fsl-nidm BIDSapps, and combined with `zip_foldernames: {${subid}: ...}` on
    the BABS side it makes the zip's top-level folder the subject directory.

    Args:
        output_dir: Derivative root (the app's output_dir)
        subject_id: Subject ID (without 'sub-' prefix)
        session_id: Session ID (without 'ses-' prefix), optional

    Returns:
        Path to the subject/session-specific output directory

    Examples:
        >>> from pathlib import Path
        >>> build_subject_output_path(Path("/output"), "01")
        PosixPath('/output/sub-01')
        >>> build_subject_output_path(Path("/output"), "01", "baseline")
        PosixPath('/output/sub-01/ses-baseline')
    """
    # Normalize labels (remove prefixes if present)
    subject_id = normalize_subject_label(subject_id)
    session_id = normalize_session_label(session_id)

    # Build path with subdirectories
    subject_dir = output_dir / f"sub-{subject_id}"

    if session_id:
        return subject_dir / f"ses-{session_id}"
    else:
        return subject_dir


# The NIDM product is ALWAYS named nidm.ttl. Subject identity is carried by the
# containing directory, never by the filename -- that is what makes the shared
# study layout work, and it is what the NIDM dataset owner asked for. Do not
# reintroduce sub-{id}.ttl / sub-{id}_ses-{x}.ttl.
NIDM_FILENAME = "nidm.ttl"


def build_nidm_filename(
    subject_id: str = None, session_id: Optional[str] = None
) -> str:
    """
    Return the canonical NIDM output filename.

    Always "nidm.ttl", regardless of subject or session -- the arguments are
    accepted only so existing call sites keep working.

    Examples:
        >>> build_nidm_filename("01")
        'nidm.ttl'
        >>> build_nidm_filename("01", "baseline")
        'nidm.ttl'
    """
    return NIDM_FILENAME


__all__ = [
    "get_nidm_data_file",
    "normalize_subject_label",
    "normalize_session_label",
    "build_subject_output_path",
    "build_nidm_filename",
    "NIDM_FILENAME",
]
