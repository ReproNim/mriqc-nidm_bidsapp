#!/usr/bin/env python
"""
NIDM Converter for MRIQC-NIDM BIDSAPP

This module handles existing NIDM file detection and copying.
Follows patterns from freesurfer_bidsapp/src/run.py for NIDM augmentation workflow.

Key features:
- Detects existing NIDM files from provided NIDM input directory
- Safely copies existing NIDM to output directory with proper subdirectory structure
- Supports NIDM augmentation workflow (adding MRIQC data to existing NIDM)

Part of the src/nidm/ package (standards compliant structure).

Author: Adapted from freesurfer_bidsapp for mriqc-nidm_bidsapp
"""

import logging
import shutil
from pathlib import Path
from typing import List, Optional


# Module-level constant for supported NIDM file extensions
SUPPORTED_NIDM_EXTENSIONS = [".ttl", ".jsonld", ".json-ld"]


def _search_nidm_in_directory(
    search_dir: Path, logger: Optional[logging.Logger] = None
) -> Optional[Path]:
    """
    Search for NIDM file in a given directory (internal helper).

    Search order (first match returned):
    1. nidm.ttl (preferred)
    2. Any *.ttl file
    3. Any *.jsonld file
    4. Any *.json-ld file

    Args:
        search_dir: Directory to search in
        logger: Optional logger instance

    Returns:
        Path to NIDM file, or None if not found
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    if not search_dir.exists():
        logger.debug(f"Search directory does not exist: {search_dir}")
        return None

    logger.debug(f"Searching for existing NIDM in: {search_dir}")

    # Prefer nidm.ttl first (convention)
    preferred = search_dir / "nidm.ttl"
    if preferred.exists():
        logger.info(f"Found existing NIDM (preferred): {preferred}")
        return preferred

    # Search for other NIDM formats in order of preference
    # Sort results for deterministic behavior across filesystems
    for ext in SUPPORTED_NIDM_EXTENSIONS:
        files = sorted(search_dir.glob(f"*{ext}"))
        if files:
            logger.info(f"Found existing NIDM ({ext.lstrip('.')}): {files[0]}")
            return files[0]

    logger.debug(f"No NIDM files found in: {search_dir}")
    return None


def detect_existing_nidm(
    subject_id: str,
    nidm_input_dir: Optional[Path] = None,
    bids_dir: Optional[Path] = None,
    logger: Optional[logging.Logger] = None
) -> Optional[Path]:
    """
    Detect existing NIDM file for subject.

    Searches for NIDM files in either the provided nidm_input_dir or the
    convention-based location (BIDS_DIR/../NIDM/sub-{subject_id}/).

    Search order (first match returned):
    1. nidm.ttl (preferred)
    2. Any *.ttl file
    3. Any *.jsonld file
    4. Any *.json-ld file

    Args:
        subject_id: Subject identifier (without "sub-" prefix)
        nidm_input_dir: Optional explicit NIDM input directory (preferred)
        bids_dir: Optional BIDS dataset directory (for convention-based lookup)
        logger: Optional logger instance

    Returns:
        Path to existing NIDM file, or None if not found

    Raises:
        ValueError: If neither nidm_input_dir nor bids_dir is provided

    Examples:
        >>> # Explicit NIDM input directory (recommended)
        >>> detect_existing_nidm('01', nidm_input_dir=Path('/data/NIDM'), logger=logger)
        Path('/data/NIDM/sub-01/nidm.ttl')

        >>> # Convention-based (backward compatibility)
        >>> detect_existing_nidm('01', bids_dir=Path('/data/BIDS'), logger=logger)
        Path('/data/NIDM/sub-01/nidm.ttl')

    Notes:
        - Returns None if NIDM directory doesn't exist (not an error)
        - Logs INFO when NIDM file found, DEBUG when not found
        - Uses pathlib for cross-platform compatibility
    """
    # Setup default logger if not provided
    if logger is None:
        logger = logging.getLogger(__name__)

    # Determine search directory
    if nidm_input_dir is not None:
        # Explicit NIDM input directory (standards-compliant)
        search_dir = nidm_input_dir / f"sub-{subject_id}"
        logger.debug(f"Using explicit NIDM input directory: {nidm_input_dir}")
    elif bids_dir is not None:
        # Convention-based location (backward compatibility)
        search_dir = bids_dir.parent / "NIDM" / f"sub-{subject_id}"
        logger.debug(f"Using convention-based NIDM location: BIDS/../NIDM/")
    else:
        raise ValueError("Either nidm_input_dir or bids_dir must be provided")

    # Use shared search logic
    return _search_nidm_in_directory(search_dir, logger)


def copy_and_prepare_nidm(
    existing_nidm: Path,
    destination_dir: Path,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """
    Safely copy existing NIDM file to output directory and prepare for augmentation.

    This function ensures that the input NIDM file is never modified by
    copying it to the output directory first. Creates necessary subdirectories
    following BIDS derivatives structure. Follows the safety-first pattern
    from freesurfer_bidsapp.

    Args:
        existing_nidm: Path to existing NIDM file
        destination_dir: Path to destination directory (includes sub-*/ses-* subdirs)
        logger: Optional logger instance

    Returns:
        Path to copied NIDM file in output directory

    Raises:
        FileNotFoundError: If existing_nidm doesn't exist
        OSError: If copy operation fails

    Examples:
        >>> copy_and_prepare_nidm(
        ...     Path('/data/NIDM/sub-01/nidm.ttl'),
        ...     Path('/output/nidm/sub-01'),
        ...     logger
        ... )
        Path('/output/nidm/sub-01/nidm.ttl')

    Notes:
        - Creates destination directory with parents if it doesn't exist
        - Preserves file metadata (timestamps, permissions)
        - Safety check prevents overwriting input file
        - Uses shutil.copy2 for metadata preservation
    """
    # Setup default logger if not provided
    if logger is None:
        logger = logging.getLogger(__name__)

    # Validate input file exists
    if not existing_nidm.exists():
        logger.error(f"Existing NIDM file not found: {existing_nidm}")
        raise FileNotFoundError(f"NIDM file not found: {existing_nidm}")

    # Create destination directory with parents if needed
    destination_dir.mkdir(parents=True, exist_ok=True)

    # Determine output path (preserve original filename)
    output_path = destination_dir / existing_nidm.name

    # Safety check: don't copy if paths are the same
    try:
        if existing_nidm.resolve() == output_path.resolve():
            logger.info(f"Input and output NIDM paths are identical: {output_path}")
            logger.info("Skipping copy to avoid unnecessary operation")
            return output_path
    except (FileNotFoundError, RuntimeError, OSError) as e:
        logger.warning(f"Could not compare paths: {e}")

    # Copy file with metadata preservation
    try:
        shutil.copy2(existing_nidm, output_path)
        logger.info(f"Copied existing NIDM to output: {output_path}")
        return output_path
    except OSError as e:
        logger.error(f"Failed to copy NIDM file: {e}")
        logger.error(f"  Source: {existing_nidm}")
        logger.error(f"  Destination: {output_path}")
        raise OSError(f"Failed to copy NIDM file: {e}") from e


def get_supported_nidm_formats() -> List[str]:
    """
    Get list of supported NIDM file extensions.

    Returns:
        List of file extensions (with dots)

    Examples:
        >>> get_supported_nidm_formats()
        ['.ttl', '.jsonld', '.json-ld']
    """
    return SUPPORTED_NIDM_EXTENSIONS


def is_nidm_file(file_path: Path) -> bool:
    """
    Check if file is a supported NIDM format.

    Args:
        file_path: Path to file

    Returns:
        True if file has supported NIDM extension

    Examples:
        >>> is_nidm_file(Path('data.ttl'))
        True

        >>> is_nidm_file(Path('data.csv'))
        False
    """
    return file_path.suffix in SUPPORTED_NIDM_EXTENSIONS
