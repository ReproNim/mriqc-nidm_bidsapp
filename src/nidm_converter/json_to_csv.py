#!/usr/bin/env python
"""
MRIQC JSON to CSV Converter

This module converts MRIQC JSON output files to CSV format suitable for NIDM conversion.
Adapted from /home/yibei/stuff2NIDM/Scripts/mriqc_json2csv.py

Key features:
- Extracts MRIQC quality metrics from JSON
- Removes unwanted metadata fields
- Extracts BIDS information (subject, session, task, run)
- Auto-generates software metadata CSV from MRIQC provenance
- Adds required fields for NIDM conversion

Author: Adapted from stuff2NIDM for mriqc-nidm_bidsapp
"""

import json
import logging
import platform
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


def remove_keys(my_dict: Dict, keys_to_remove: List[str]) -> Dict:
    """
    Create a new dictionary without the specified keys.

    This is a pure function that does not modify the input dictionary,
    avoiding side effects and making the behavior more predictable.

    Args:
        my_dict: The dictionary to remove keys from
        keys_to_remove: A list of keys to remove

    Returns:
        A new dictionary with the specified keys removed
    """
    return {key: value for key, value in my_dict.items() if key not in keys_to_remove}


def create_software_metadata_csv(
    json_data: Dict, csv_file_path: Path, logger: logging.Logger
) -> Path:
    """
    Create dynamic software metadata CSV from MRIQC JSON provenance.

    Extracts software information from the MRIQC JSON provenance field
    and generates a software metadata CSV file for NIDM conversion.

    Args:
        json_data: Loaded MRIQC JSON data
        csv_file_path: Path to the output CSV file (used to derive metadata filename)
        logger: Logger instance

    Returns:
        Path to the created software metadata CSV file

    Example output fields:
        - title: 'mriqc'
        - version: '23.1.0'
        - url: 'https://mriqc.readthedocs.io/en/stable/'
        - platform: 'Linux 5.15.0'
        - ID: 'https://scicrunch.org/resolver/RRID:SCR_022942'
    """
    # Extract from provenance if available
    if "provenance" in json_data:
        prov = json_data["provenance"]
        software = prov.get("software", "mriqc")
        version = prov.get("version", "unknown")
    else:
        logger.warning("No provenance field found in JSON, using defaults")
        software = "mriqc"
        version = "unknown"

    # Get system platform info
    platform_info = f"{platform.system()} {platform.release()}"

    # Create software metadata
    software_metadata = {
        "title": software,
        "description": (
            "MRIQC extracts no-reference IQMs (image quality metrics) from "
            "structural (T1w and T2w), functional and diffusion MRI data."
        ),
        "version": version,
        "url": "https://mriqc.readthedocs.io/en/stable/",
        "cmdline": f"{software} --version {version}",  # Simplified cmdline
        "platform": platform_info,
        "ID": "https://scicrunch.org/resolver/RRID:SCR_022942",
    }

    # Write to CSV (use pathlib for robust filename generation)
    df_software = pd.DataFrame(software_metadata, index=[0])
    software_csv_path = csv_file_path.with_name(
        f"{csv_file_path.stem}_software_metadata.csv"
    )
    df_software.to_csv(software_csv_path, index=False)

    logger.info(f"Created software metadata: {software_csv_path}")
    logger.debug(f"  Software: {software} {version}")
    logger.debug(f"  Platform: {platform_info}")

    return software_csv_path


def extract_bids_info(
    json_file_path: Path, json_data: Dict, logger: logging.Logger
) -> Tuple[str, str, str, str]:
    """
    Extract BIDS information from file path and JSON metadata.

    Attempts to extract subject, session, task, and run information from:
    1. BIDS metadata in the JSON file (if available)
    2. File path parsing (fallback)

    Args:
        json_file_path: Path to the MRIQC JSON file
        json_data: Loaded MRIQC JSON data
        logger: Logger instance

    Returns:
        Tuple of (subject_id, session, task, run)

    Examples:
        >>> extract_bids_info(Path('sub-01_ses-01_T1w.json'), {}, logger)
        ('01', '01', 'None', '')

        >>> extract_bids_info(Path('sub-02_task-rest_run-1_bold.json'), {}, logger)
        ('02', '01', 'rest', '1')
    """
    # Extract from BIDS metadata if available
    if "bids_meta" in json_data:
        bids_meta = json_data["bids_meta"]
        subj = bids_meta.get("subject", "unknown")
        datatype = bids_meta.get("datatype", "unknown")
        logger.debug(f"Extracted subject from bids_meta: {subj}")
    else:
        # Fallback to filename parsing
        filename = json_file_path.name
        subj = "unknown"

        # Infer datatype from filename for more robust task assignment
        if "_T1w" in filename or "_T2w" in filename:
            datatype = "anat"
        elif "_bold" in filename:
            datatype = "func"
        else:
            datatype = "unknown"

        # Parse BIDS filename pattern for subject
        if filename.startswith("sub-"):
            subj = filename.split("_")[0].replace("sub-", "")
            logger.debug(f"Extracted subject from filename: {subj}")

    # Extract session, task, run from file path and filename
    # Use pathlib.parts for cross-platform compatibility (works on Windows/Unix)
    path_parts = json_file_path.parts
    filename = json_file_path.name
    ses = None
    task = None
    run = None

    # Look for session in path (ses-XX)
    for part in path_parts:
        if part.startswith("ses-"):
            ses = part.replace("ses-", "")
            break

    # If not found in path, look for session in filename (ses-XX)
    if ses is None:
        ses_match = re.search(r"ses-([^_]+)", filename)
        if ses_match:
            ses = ses_match.group(1)

    # Look for task in filename (task-XX)
    task_match = re.search(r"task-([^_]+)", filename)
    if task_match:
        task = task_match.group(1)
    else:
        # For anatomical data, task is typically None
        task = "None" if datatype == "anat" else ""

    # Look for run in filename (run-XX)
    run_match = re.search(r"run-([^_]+)", filename)
    if run_match:
        run = run_match.group(1)
    else:
        run = ""

    # Use session 01 as default if not found
    if ses is None:
        ses = "01"
        logger.debug("No session found in path or filename, defaulting to '01'")

    logger.info(f"Extracted BIDS info: subject={subj}, session={ses}, task={task}, run={run}")

    return subj, ses, task, run


def convert_mriqc_json_to_csv(
    json_file: Path,
    output_csv: Path,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Path, Path]:
    """
    Convert MRIQC JSON output to CSV format with auto-generated metadata.

    This is the main conversion function that orchestrates the entire
    JSON to CSV transformation process.

    Process:
    1. Load MRIQC JSON file
    2. Extract software metadata from provenance
    3. Remove unwanted fields (bids_meta, provenance, qi_*, size_*, spacing_*)
    4. Extract BIDS information from file path and metadata
    5. Add required NIDM fields (subject_id, ses, task, run, source_url)
    6. Write to CSV file

    Args:
        json_file: Path to MRIQC JSON file
        output_csv: Path for output CSV file
        logger: Logger instance (creates default if not provided)

    Returns:
        Tuple of (csv_path, software_metadata_csv_path)

    Raises:
        FileNotFoundError: If JSON file doesn't exist
        json.JSONDecodeError: If JSON file is malformed
        Exception: For other processing errors

    Example:
        >>> csv_path, metadata_path = convert_mriqc_json_to_csv(
        ...     Path('sub-01_T1w.json'),
        ...     Path('sub-01_mriqc.csv')
        ... )
    """
    # Setup logger if not provided
    if logger is None:
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(levelname)s: %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)

    logger.info(f"Converting MRIQC JSON to CSV: {json_file} -> {output_csv}")

    # Read the JSON file
    try:
        with open(json_file, "r") as f:
            data = json.load(f)
        logger.debug(f"Successfully loaded JSON file with {len(data)} fields")
    except FileNotFoundError:
        logger.error(f"JSON file not found: {json_file}")
        raise FileNotFoundError(f"Error: JSON file not found at '{json_file}'")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in file: {json_file}")
        raise json.JSONDecodeError(
            f"Error: Invalid JSON format in the file: {e.msg}", e.doc, e.pos
        )

    # Create software metadata CSV BEFORE removing provenance
    software_csv_path = create_software_metadata_csv(data, output_csv, logger)

    # Define keys to remove (unwanted fields)
    keys_to_drop = [
        "bids_meta",
        "provenance",
        "qi_1",
        "qi_2",
        "size_x",
        "size_y",
        "size_z",
        "spacing_x",
        "spacing_y",
        "spacing_z",
    ]

    # Remove unwanted keys (remove_keys is a pure function, no need for .copy())
    updated_data = remove_keys(data, keys_to_drop)
    logger.debug(f"Removed {len(keys_to_drop)} unwanted fields")

    # Extract BIDS information
    subj, ses, task, run = extract_bids_info(json_file, data, logger)
    source_url = str(json_file)  # Use the full path as source URL

    # Add required NIDM fields (ensure subject_id stays as string)
    updated_data.update(
        {
            "subject_id": str(subj),  # Explicitly convert to string to prevent int conversion
            "ses": str(ses),
            "task": str(task),
            "run": str(run),
            "source_url": source_url,
        }
    )

    # Convert to DataFrame and write to CSV
    df = pd.DataFrame(updated_data, index=[0])

    # Ensure BIDS identifier columns are preserved as strings (not converted to int)
    string_columns = ["subject_id", "ses", "task", "run"]
    for col in string_columns:
        if col in df.columns:
            df[col] = df[col].astype(str)

    df.to_csv(output_csv, index=False)

    logger.info(f"Successfully created CSV: {output_csv}")
    logger.info(f"  Fields: {len(df.columns)}")
    logger.info(f"  Rows: {len(df)}")

    return output_csv, software_csv_path


# Command-line interface (for standalone usage)
if __name__ == "__main__":
    import argparse
    import sys

    # Setup logging for CLI
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    # Parse command line arguments with argparse for better usability
    parser = argparse.ArgumentParser(
        description="Convert MRIQC JSON output to CSV format for NIDM conversion.",
        epilog="Example: python json_to_csv.py sub-01_T1w.json sub-01_mriqc.csv",
    )
    parser.add_argument(
        "json_file",
        type=Path,
        help="Path to the input MRIQC JSON file",
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="Path to the output CSV file",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG level) logging",
    )

    args = parser.parse_args()

    # Adjust logging level if verbose
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        csv_path, metadata_path = convert_mriqc_json_to_csv(
            args.json_file, args.csv_file, logger
        )
        print(f"\nSuccess!")
        print(f"  CSV: {csv_path}")
        print(f"  Metadata: {metadata_path}")
    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        sys.exit(1)
