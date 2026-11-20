"""
Utility functions for MRIQC-NIDM BIDSapp.

This module provides general utility functions used across the MRIQC-NIDM application
including label normalization, argument parsing, logging setup, and BIDS
metadata creation.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# BIDS specification version declared in the dataset_description.json files this
# app writes. This is the *spec* version, never a library version (pybids'
# __version__ is the library, not the spec -- conflating the two is the bug this
# constant exists to prevent). Kept in sync with freesurfer-nidm_bidsapp.
BIDS_VERSION = "1.8.0"


def not_fetched(path: Path) -> bool:
    """A git-annex file whose content is not here: a broken symlink (locked)
    or a small pointer file naming the annex object (unlocked)."""
    if not path.exists():
        return True
    if path.stat().st_size > 1024:
        return False
    return path.read_bytes().startswith(b"/annex/objects/")


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


# MRIQC's long options as its parser spells them. Taken from mriqc/cli/parser.py
# of nipreps/mriqc at the version the Dockerfile and Singularity image pin
# (the Python side of that pin is MRIQC_OPTIONS_VERSION, checked against both
# files by tests/test_run.py); revisit this table when the pin moves.
# MRIQC treats - and _ as different characters: most options have dashes only,
# a few have underscores only (fd_thres, n_procs, n_cpus, mem_gb), and
# participant-label has all four spellings, singular and plural.
MRIQC_OPTIONS_VERSION = "25.0.0rc0"
MRIQC_LONG_OPTIONS = frozenset({
    "ants-float",
    "ants-nthreads",
    "ants-settings",
    "bids-database-dir",
    "bids-database-wipe",
    "bids-filter-file",
    "crashfile-format",
    "deoblique",
    "despike",
    "dry-run",
    "dsname",
    "email",
    "fd_thres",
    "fft-spikes-detector",
    "float32",
    "mem",
    "mem-gb",
    "mem_gb",
    "min-bold-length",
    "min-dwi-length",
    "modalities",
    "n_cpus",
    "n_procs",
    "no-datalad-get",
    "no-sub",
    "notrack",
    "nprocs",
    "omp-nthreads",
    "participant-label",
    "participant-labels",
    "participant_label",
    "participant_labels",
    "pdb",
    "profile",
    "reports-only",
    "resource-monitor",
    "run-id",
    "session-id",
    "species",
    "start-idx",
    "stop-idx",
    "task-id",
    "testing",
    "upload-strict",
    "use-plugin",
    "verbose",
    "verbose-reports",
    "webapi-port",
    "webapi-url",
    "work-dir",
    "write-graph",
})


def mriqc_spelling(typed: str) -> str:
    """The spelling MRIQC accepts for an option typed as ``typed`` (without the leading ``--``).

    MRIQC treats - and _ as different characters and spells a few options with
    underscores (fd_thres, n_procs, n_cpus, mem_gb). A typed name MRIQC does
    not define but whose other spelling it does is respelled; an abbreviation
    or an option this table lacks goes through as typed.
    """
    if typed in MRIQC_LONG_OPTIONS:
        return typed
    for other in (typed.replace("-", "_"), typed.replace("_", "-")):
        if other in MRIQC_LONG_OPTIONS:
            return other
    return typed


class PassThroughKey(str):
    """An underscored option name that remembers the flag for MRIQC.

    It compares and hashes as the plain name (``fd_thres``), so lookups by
    name keep working, while ``flag`` is what goes back on MRIQC's command
    line, in the spelling MRIQC defines (see ``mriqc_spelling``).
    """

    flag: str

    def __new__(cls, name: str, flag: str):
        obj = super().__new__(cls, name)
        obj.flag = flag
        return obj

    def __getnewargs__(self):
        # str's own would drop the flag, and copy and pickle rebuild with it.
        return (str(self), self.flag)


# MRIQC options the app owns, with the app option to use instead. The keys are
# the longest spelling of each, in underscore form: MRIQC's argparse accepts
# any unambiguous prefix of an option string, so every prefix of a key is
# claimed too (--participant_lab, --session-i). MRIQC's four participant-label
# spellings all end up in the key "participant_labels" or a prefix of it.
# --session_label is the app's own --session-label with an underscore, which
# MRIQC does not define either.
_OWNED_MRIQC_OPTIONS = {
    "participant_labels": "--participant-label",
    "session_id": "--session-label",
    "session_label": "--session-label",
}


def owned_mriqc_option(extra_args: List[str]) -> Optional[Tuple[str, str]]:
    """The first pass-through flag that names an option the app owns.

    Returns ``(flag as typed, app option to use)``, or None. Only an option's
    own name is read, never a value.
    """
    for arg in extra_args:
        if not arg.startswith("--"):
            continue
        typed = arg.partition("=")[0]
        name = typed[2:].replace("-", "_")
        if not name:
            continue
        for owned, instead in _OWNED_MRIQC_OPTIONS.items():
            if owned.startswith(name):
                return typed, instead
    return None


def parse_mriqc_args(extra_args: List[str]) -> Dict[str, Any]:
    """
    Parse MRIQC extra arguments into kwargs dictionary.

    Converts command-line style arguments into a dictionary suitable for
    passing to MRIQCWrapper. Handles both key-value pairs and boolean flags.
    Values stay strings: they only go back onto MRIQC's command line, and a
    BIDS label such as ``--task-id 01`` is not the number 1. (MRIQC's own
    numeric options are not known here, so none is converted.)

    Examples:
        >>> parse_mriqc_args(['--mem', '16G', '--nprocs', '12'])
        {'mem': '16G', 'nprocs': '12'}
        >>> parse_mriqc_args(['--ica', '--no-sub'])
        {'ica': True, 'no_sub': True}
        >>> parse_mriqc_args(['-m', 'T1w', 'bold', '--bids-filter-file=f.json'])
        {'modalities': ['T1w', 'bold'], 'bids_filter_file': 'f.json'}

    Args:
        extra_args: List of command-line arguments not recognized by mriqc-nidm

    Returns:
        Dictionary of parsed arguments with underscored keys
    """
    mriqc_kwargs: Dict[str, Any] = {}
    i = 0
    while i < len(extra_args):
        arg = extra_args[i]
        # MRIQC's -m is its only short option that takes values; others
        # (-w, -v) are not passed through.
        if arg == "-m":
            arg = "--modalities"
        if not arg.startswith("--"):
            i += 1
            continue
        typed, eq, inline = arg[2:].partition("=")
        # --omp-nthreads → omp_nthreads, remembering the flag MRIQC defines.
        key = PassThroughKey(typed.replace("-", "_"), f"--{mriqc_spelling(typed)}")
        if eq:
            # --bids-filter-file=/x/f.json: the value is part of the flag.
            mriqc_kwargs[key] = inline
            i += 1
            continue
        # Every value up to the next flag: --modalities T1w bold takes both.
        values = []
        i += 1
        while i < len(extra_args) and not extra_args[i].startswith("-"):
            values.append(extra_args[i])
            i += 1
        if not values:
            mriqc_kwargs[key] = True  # Boolean flag
        elif len(values) == 1:
            mriqc_kwargs[key] = values[0]
        else:
            mriqc_kwargs[key] = values
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
    version: str = "unknown",
    logger: logging.Logger = None
) -> Path:
    """
    Create dataset_description.json at the derivative root.

    Written beside the sub-* directories, NOT inside them: the per-subject
    directory is what BABS zips, so a copy placed there would be duplicated into
    every subject's zip and the copies would fight over the same path on merge.

    Args:
        output_dir: Derivative root (the app's output_dir)
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

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_desc = {
        "Name": "MRIQC Quality Control Metrics (NIDM)",
        "BIDSVersion": BIDS_VERSION,
        "DatasetType": "derivative",
        "GeneratedBy": [
            {
                "Name": "MRIQC-NIDM BIDSAPP",
                "Version": version,
                "CodeURL": "https://github.com/ReproNim/mriqc-nidm_bidsapp"
            }
        ],
        "HowToAcknowledge": (
            "Please cite MRIQC (https://doi.org/10.1371/journal.pone.0184661) "
            "and NIDM (http://nidm.nidash.org/)"
        ),
    }

    desc_file = output_dir / "dataset_description.json"
    with open(desc_file, "w") as f:
        json.dump(dataset_desc, f, indent=2)

    logger.info(f"Created dataset_description.json: {desc_file}")
    return desc_file


__all__ = [
    "BIDS_VERSION",
    "normalize_label",
    "normalize_participant_labels",
    "normalize_session_labels",
    "MRIQC_LONG_OPTIONS",
    "MRIQC_OPTIONS_VERSION",
    "PassThroughKey",
    "mriqc_spelling",
    "owned_mriqc_option",
    "parse_mriqc_args",
    "setup_logging",
    "create_dataset_description",
]
