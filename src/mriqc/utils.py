"""
Utility functions for MRIQC-NIDM BIDSapp.

This module provides general utility functions used across the MRIQC-NIDM application
including label normalization, argument parsing, logging setup, and BIDS metadata creation.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def normalize_label(label: str, prefix: str) -> str:
    """
    Normalize a BIDS label by stripping prefix if present.

    Makes the code robust to both formats:
    - With prefix: 'sub-0051456' → '0051456'
    - Without prefix: '0051456' → '0051456'

    Args:
        label: The label to normalize
        prefix: The prefix to strip (e.g., 'sub-', 'ses-')

    Returns:
        Label without the prefix

    Examples:
        >>> normalize_label('sub-01', 'sub-')
        '01'
        >>> normalize_label('01', 'sub-')
        '01'
    """
    return label[len(prefix):] if label.startswith(prefix) else label


def normalize_participant_labels(labels: List[str]) -> List[str]:
    """
    Normalize participant labels by removing 'sub-' prefix.

    Args:
        labels: List of participant labels (with or without 'sub-' prefix)

    Returns:
        List of labels without prefix

    Examples:
        >>> normalize_participant_labels(['sub-01', 'sub-02'])
        ['01', '02']
        >>> normalize_participant_labels(['01', '02'])
        ['01', '02']
    """
    return [normalize_label(label, 'sub-') for label in labels]


def normalize_session_labels(labels: List[str]) -> List[str]:
    """
    Normalize session labels by removing 'ses-' prefix.

    Args:
        labels: List of session labels (with or without 'ses-' prefix)

    Returns:
        List of labels without prefix

    Examples:
        >>> normalize_session_labels(['ses-baseline', 'ses-followup'])
        ['baseline', 'followup']
        >>> normalize_session_labels(['baseline', 'followup'])
        ['baseline', 'followup']
    """
    return [normalize_label(label, 'ses-') for label in labels]


def parse_mriqc_args(extra_args: List[str]) -> Dict[str, Any]:
    """
    Parse MRIQC extra arguments into kwargs dictionary.

    Converts command-line style arguments into a dictionary suitable for
    passing to MRIQCWrapper. Handles both key-value pairs and boolean flags.

    Examples:
        >>> parse_mriqc_args(['--mem', '16G', '--nprocs', '12'])
        {'mem': '16G', 'nprocs': 12}
        >>> parse_mriqc_args(['--ica', '--no-sub'])
        {'ica': True, 'no_sub': True}

    Args:
        extra_args: List of command-line arguments not recognized by mriqc-nidm

    Returns:
        Dictionary of parsed arguments with underscored keys
    """
    mriqc_kwargs: Dict[str, Any] = {}
    i = 0
    while i < len(extra_args):
        arg = extra_args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")  # --omp-nthreads → omp_nthreads
            # Check if next arg is a value or another flag
            if i + 1 < len(extra_args) and not extra_args[i + 1].startswith("-"):
                value: Any = extra_args[i + 1]
                # Try to convert to int/float if possible
                try:
                    value = int(value)
                except ValueError:
                    try:
                        value = float(value)
                    except ValueError:
                        pass  # Keep as string
                mriqc_kwargs[key] = value
                i += 2
            else:
                # Boolean flag
                mriqc_kwargs[key] = True
                i += 1
        else:
            i += 1
    return mriqc_kwargs


def setup_logging(
    output_dir: Path,
    verbose: bool = False,
    version: str = "unknown"
) -> logging.Logger:
    """
    Set up logging configuration.

    Creates a timestamped log file in the output directory and configures
    both file and console logging handlers.

    Args:
        output_dir: Output directory for log files
        verbose: Enable verbose (DEBUG) logging
        version: Application version to log

    Returns:
        Configured logger instance

    Examples:
        >>> logger = setup_logging(Path('/output'), verbose=True, version='0.2.0')
        >>> logger.info("Processing started")
    """
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"mriqc-nidm-{timestamp}.log"

    level = logging.DEBUG if verbose else logging.INFO

    # Configure root logger
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    logger = logging.getLogger("mriqc-nidm")
    logger.info(f"MRIQC-NIDM BIDSAPP version {version}")
    logger.info(f"Log file: {log_file}")

    return logger


def create_dataset_description(
    output_dir: Path,
    app_name: str = "mriqc-nidm_bidsapp",
    version: str = "unknown",
    logger: logging.Logger = None
) -> Path:
    """
    Create dataset_description.json for NIDM derivatives.

    Args:
        output_dir: Output directory
        app_name: Application name (used in directory structure)
        version: Application version
        logger: Optional logger instance

    Returns:
        Path to created dataset_description.json

    Examples:
        >>> desc_path = create_dataset_description(Path('/output'))
        >>> desc_path.exists()
        True
    """
    import json

    if logger is None:
        logger = logging.getLogger(__name__)

    nidm_dir = output_dir / app_name / "nidm"
    nidm_dir.mkdir(parents=True, exist_ok=True)

    dataset_desc = {
        "Name": "MRIQC Quality Control Metrics (NIDM)",
        "BIDSVersion": "1.6.0",
        "DatasetType": "derivative",
        "GeneratedBy": [
            {
                "Name": "MRIQC-NIDM BIDSAPP",
                "Version": version,
                "CodeURL": "https://github.com/sensein/mriqc-nidm_bidsapp"
            }
        ],
        "HowToAcknowledge": "Please cite MRIQC (https://doi.org/10.1371/journal.pone.0184661) and NIDM (http://nidm.nidash.org/)",
    }

    desc_file = nidm_dir / "dataset_description.json"
    with open(desc_file, "w") as f:
        json.dump(dataset_desc, f, indent=2)

    logger.info(f"Created dataset_description.json: {desc_file}")
    return desc_file


__all__ = [
    "normalize_label",
    "normalize_participant_labels",
    "normalize_session_labels",
    "parse_mriqc_args",
    "setup_logging",
    "create_dataset_description",
]
