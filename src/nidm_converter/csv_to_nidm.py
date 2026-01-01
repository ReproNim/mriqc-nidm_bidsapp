#!/usr/bin/env python
"""
CSV to NIDM Converter for MRIQC-NIDM BIDSAPP

This module wraps the csv2nidm command-line tool from PyNIDM to convert
MRIQC CSV results to NIDM format. Supports both standalone NIDM creation
and augmentation of existing NIDM files.

Key features:
- Wraps csv2nidm tool with proper error handling
- Supports standalone mode (new NIDM creation)
- Supports augmentation mode (add to existing NIDM)
- Validates tool availability and input files
- Comprehensive logging integration
- CLI support for standalone usage

Author: Adapted from plan_revision.md for mriqc-nidm_bidsapp
"""

import argparse
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional


# Module-level constants
CSV2NIDM_TOOL = "csv2nidm"
TIMEOUT_SECONDS = 300


def check_csv2nidm_available() -> bool:
    """
    Check if csv2nidm tool is available in PATH.

    Returns:
        True if csv2nidm is available, False otherwise

    Examples:
        >>> check_csv2nidm_available()
        True
    """
    return shutil.which(CSV2NIDM_TOOL) is not None


def convert_csv_to_nidm(
    csv_file: Path,
    dictionary_csv: Path,
    software_metadata_csv: Path,
    output_ttl: Path,
    existing_nidm: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    Convert CSV to NIDM using csv2nidm tool.

    This function wraps the csv2nidm command-line tool to convert MRIQC
    results in CSV format to NIDM (Neuroimaging Data Model) format.
    Supports both creating new NIDM files and augmenting existing ones.

    Args:
        csv_file: Path to MRIQC results in CSV format
        dictionary_csv: Path to data dictionary mapping file
        software_metadata_csv: Path to software provenance metadata
        output_ttl: Path for output NIDM file (Turtle format)
        existing_nidm: Optional path to existing NIDM file to augment
        logger: Optional logger instance

    Returns:
        True if conversion is successful

    Raises:
        FileNotFoundError: If csv2nidm tool is not available
        FileNotFoundError: If required input files don't exist
        RuntimeError: If csv2nidm execution fails

    Examples:
        >>> # Create new NIDM
        >>> convert_csv_to_nidm(
        ...     csv_file=Path('mriqc_results.csv'),
        ...     dictionary_csv=Path('mriqc_dictionary_v1.csv'),
        ...     software_metadata_csv=Path('software_metadata.csv'),
        ...     output_ttl=Path('output/sub-01.ttl'),
        ...     logger=logger
        ... )
        True

        >>> # Augment existing NIDM
        >>> convert_csv_to_nidm(
        ...     csv_file=Path('mriqc_results.csv'),
        ...     dictionary_csv=Path('mriqc_dictionary_v1.csv'),
        ...     software_metadata_csv=Path('software_metadata.csv'),
        ...     output_ttl=Path('output/sub-01.ttl'),
        ...     existing_nidm=Path('input/existing.ttl'),
        ...     logger=logger
        ... )
        True

    Notes:
        - When existing_nidm is provided, csv2nidm uses -nidm flag (augmentation mode)
        - When existing_nidm is None, csv2nidm uses -out flag (standalone mode)
        - The -no_concepts flag is always used to skip InterLex concept lookup
        - The -derivative flag indicates this is derivative data with BIDS metadata
        - Output directory is created if it doesn't exist
    """
    # Setup default logger if not provided
    if logger is None:
        logger = logging.getLogger(__name__)

    # Check if csv2nidm tool is available
    if not check_csv2nidm_available():
        logger.error(f"{CSV2NIDM_TOOL} tool not found in PATH")
        raise FileNotFoundError(
            f"{CSV2NIDM_TOOL} not available. Install PyNIDM package."
        )

    # Validate input files exist
    for file_path, file_desc in [
        (csv_file, "CSV file"),
        (dictionary_csv, "Dictionary CSV"),
        (software_metadata_csv, "Software metadata CSV"),
    ]:
        if not file_path.exists():
            logger.error(f"{file_desc} not found: {file_path}")
            raise FileNotFoundError(f"{file_desc} not found: {file_path}")

    # Validate existing NIDM if provided
    if existing_nidm and not existing_nidm.exists():
        logger.error(f"Existing NIDM file not found: {existing_nidm}")
        raise FileNotFoundError(f"Existing NIDM file not found: {existing_nidm}")

    # Create output directory if needed
    output_ttl.parent.mkdir(parents=True, exist_ok=True)

    # Build csv2nidm command
    cmd = [CSV2NIDM_TOOL]

    if existing_nidm:
        # Augment existing NIDM
        cmd.extend(["-nidm", str(existing_nidm)])
        logger.info(f"Augmenting existing NIDM: {existing_nidm}")
    else:
        # Create new NIDM
        cmd.extend(["-out", str(output_ttl)])
        logger.info(f"Creating new NIDM: {output_ttl}")

    # Add required arguments
    cmd.extend(
        [
            "-csv",
            str(csv_file),
            "-csv_map",
            str(dictionary_csv),
            "-derivative",
            str(software_metadata_csv),
            "-no_concepts",
        ]
    )

    logger.debug(f"Executing command: {' '.join(cmd)}")

    # Execute csv2nidm
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as e:
        logger.error(f"csv2nidm timed out after {TIMEOUT_SECONDS} seconds")
        raise RuntimeError(f"csv2nidm execution timed out: {e}") from e
    except subprocess.CalledProcessError as e:
        logger.error(f"csv2nidm failed with return code {e.returncode}")
        logger.error(f"stdout: {e.stdout}")
        logger.error(f"stderr: {e.stderr}")
        raise RuntimeError(
            f"csv2nidm failed: {e.stderr or e.stdout or 'Unknown error'}"
        ) from e
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f"Failed to execute csv2nidm: {e}")
        raise RuntimeError(f"csv2nidm execution failed: {e}") from e

    # Log success
    if existing_nidm:
        logger.info(f"Successfully augmented NIDM with MRIQC data")
    else:
        logger.info(f"Successfully created NIDM: {output_ttl}")

    # Log any warnings from stdout
    if result.stdout:
        logger.debug(f"csv2nidm output: {result.stdout}")

    return True


def main():
    """
    Command-line interface for csv_to_nidm converter.

    Provides standalone CLI for testing and debugging the csv2nidm wrapper.
    """
    parser = argparse.ArgumentParser(
        description="Convert MRIQC CSV to NIDM format using csv2nidm tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "csv_file", type=Path, help="Path to MRIQC results CSV file"
    )

    parser.add_argument(
        "dictionary_csv", type=Path, help="Path to data dictionary CSV file"
    )

    parser.add_argument(
        "software_metadata_csv",
        type=Path,
        help="Path to software metadata CSV file",
    )

    parser.add_argument(
        "output_ttl", type=Path, help="Path for output NIDM file (Turtle format)"
    )

    parser.add_argument(
        "--existing-nidm",
        type=Path,
        help="Path to existing NIDM file to augment (optional)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Convert CSV to NIDM
    try:
        convert_csv_to_nidm(
            csv_file=args.csv_file,
            dictionary_csv=args.dictionary_csv,
            software_metadata_csv=args.software_metadata_csv,
            output_ttl=args.output_ttl,
            existing_nidm=args.existing_nidm,
            logger=logger,
        )
        logger.info("Conversion completed successfully")
        return 0

    except (FileNotFoundError, RuntimeError) as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
