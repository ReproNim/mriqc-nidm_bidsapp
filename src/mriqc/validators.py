"""
Validation functions for BIDS datasets and arguments.

This module provides validation utilities for checking BIDS dataset structure,
NIDM input directories, and output directories used in the MRIQC-NIDM pipeline.
"""

import logging
from pathlib import Path
from typing import Optional, List


def validate_bids_directory(bids_dir: Path, logger: Optional[logging.Logger] = None) -> bool:
    """
    Validate BIDS directory structure.

    Checks for essential BIDS components:
    - Directory exists
    - dataset_description.json exists
    - At least one subject directory (sub-*) exists

    Args:
        bids_dir: Path to BIDS dataset directory
        logger: Optional logger instance

    Returns:
        True if valid BIDS directory, False otherwise

    Examples:
        >>> validate_bids_directory(Path('/data/my_bids_dataset'))
        True
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # Check directory exists
    if not bids_dir.exists():
        logger.error(f"BIDS directory does not exist: {bids_dir}")
        return False

    if not bids_dir.is_dir():
        logger.error(f"BIDS path is not a directory: {bids_dir}")
        return False

    # Check for dataset_description.json
    dataset_desc = bids_dir / "dataset_description.json"
    if not dataset_desc.exists():
        logger.warning(f"BIDS dataset_description.json not found: {dataset_desc}")
        logger.warning("This may not be a valid BIDS dataset")
        return False

    # Check for at least one subject directory
    subject_dirs = list(bids_dir.glob("sub-*"))
    if not subject_dirs:
        logger.warning(f"No subject directories found in BIDS dataset: {bids_dir}")
        return False

    logger.debug(f"Valid BIDS directory: {bids_dir} ({len(subject_dirs)} subjects)")
    return True


def validate_nidm_input_directory(
    nidm_dir: Path,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Validate NIDM input directory.

    Checks for:
    - Directory exists
    - Contains at least one NIDM file (.ttl, .jsonld, or .json-ld)

    Args:
        nidm_dir: Path to NIDM input directory
        logger: Optional logger instance

    Returns:
        True if directory exists and contains NIDM files, False otherwise

    Examples:
        >>> validate_nidm_input_directory(Path('/data/NIDM'))
        True
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # Check directory exists
    if not nidm_dir.exists():
        logger.warning(f"NIDM input directory does not exist: {nidm_dir}")
        return False

    if not nidm_dir.is_dir():
        logger.error(f"NIDM input path is not a directory: {nidm_dir}")
        return False

    # Check for NIDM files (*.ttl, *.jsonld, *.json-ld)
    # Search recursively to handle sub-01/, sub-01/ses-01/, etc.
    nidm_extensions = [".ttl", ".jsonld", ".json-ld"]
    nidm_files = []
    for ext in nidm_extensions:
        nidm_files.extend(nidm_dir.rglob(f"*{ext}"))

    if not nidm_files:
        logger.warning(f"No NIDM files found in: {nidm_dir}")
        logger.warning("Expected extensions: .ttl, .jsonld, .json-ld")
        return False

    logger.debug(f"Valid NIDM directory: {nidm_dir} ({len(nidm_files)} NIDM files)")
    return True


def validate_output_directory(
    output_dir: Path,
    create: bool = True,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Validate and optionally create output directory.

    Args:
        output_dir: Path to output directory
        create: Create directory if it doesn't exist (default: True)
        logger: Optional logger instance

    Returns:
        True if directory exists/created successfully and is writable, False otherwise

    Raises:
        PermissionError: If directory cannot be created or is not writable

    Examples:
        >>> validate_output_directory(Path('/output'))
        True
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # Create directory if requested and doesn't exist
    if not output_dir.exists() and create:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created output directory: {output_dir}")
        except PermissionError as e:
            logger.error(f"Cannot create output directory: {e}")
            return False
        except OSError as e:
            logger.error(f"Failed to create output directory: {e}")
            return False

    # Check directory exists
    if not output_dir.exists():
        logger.error(f"Output directory does not exist: {output_dir}")
        return False

    # Check it's actually a directory
    if not output_dir.is_dir():
        logger.error(f"Output path is not a directory: {output_dir}")
        return False

    # Check write permissions
    if not access_check_writable(output_dir):
        logger.error(f"Output directory is not writable: {output_dir}")
        return False

    logger.debug(f"Valid output directory: {output_dir}")
    return True


def access_check_writable(directory: Path) -> bool:
    """
    Check if directory is writable.

    Args:
        directory: Path to directory to check

    Returns:
        True if writable, False otherwise

    Examples:
        >>> access_check_writable(Path('/tmp'))
        True
    """
    try:
        test_file = directory / ".write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except (PermissionError, OSError):
        return False


def validate_participant_labels(labels: List[str]) -> List[str]:
    """
    Validate and normalize participant labels.

    Ensures labels don't contain invalid characters and normalizes
    by removing 'sub-' prefix if present.

    Args:
        labels: List of participant labels

    Returns:
        List of normalized labels

    Raises:
        ValueError: If any label contains invalid characters

    Examples:
        >>> validate_participant_labels(['sub-01', '02'])
        ['01', '02']
    """
    import re

    normalized = []
    for label in labels:
        # Remove 'sub-' prefix if present
        clean_label = label[4:] if label.startswith('sub-') else label

        # Check for invalid characters (BIDS allows alphanumeric and underscore)
        if not re.match(r'^[a-zA-Z0-9_]+$', clean_label):
            raise ValueError(
                f"Invalid participant label '{label}': "
                f"Only alphanumeric characters and underscores allowed"
            )

        normalized.append(clean_label)

    return normalized


def validate_session_labels(labels: List[str]) -> List[str]:
    """
    Validate and normalize session labels.

    Ensures labels don't contain invalid characters and normalizes
    by removing 'ses-' prefix if present.

    Args:
        labels: List of session labels

    Returns:
        List of normalized labels

    Raises:
        ValueError: If any label contains invalid characters

    Examples:
        >>> validate_session_labels(['ses-baseline', 'followup'])
        ['baseline', 'followup']
    """
    import re

    normalized = []
    for label in labels:
        # Remove 'ses-' prefix if present
        clean_label = label[4:] if label.startswith('ses-') else label

        # Check for invalid characters (BIDS allows alphanumeric and underscore)
        if not re.match(r'^[a-zA-Z0-9_]+$', clean_label):
            raise ValueError(
                f"Invalid session label '{label}': "
                f"Only alphanumeric characters and underscores allowed"
            )

        normalized.append(clean_label)

    return normalized


__all__ = [
    "validate_bids_directory",
    "validate_nidm_input_directory",
    "validate_output_directory",
    "access_check_writable",
    "validate_participant_labels",
    "validate_session_labels",
]
