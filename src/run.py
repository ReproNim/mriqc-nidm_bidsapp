#!/usr/bin/env python3
"""
Main entry point for MRIQC-NIDM BIDSAPP.

This module orchestrates the complete workflow:
1. Detect existing NIDM files (optional)
2. Run MRIQC quality control
3. Convert MRIQC JSON outputs to CSV
4. Convert CSV to NIDM format
5. Support augmentation of existing NIDM files

Follows BIDS Apps specification and patterns from freesurfer_bidsapp.
"""

import argparse
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .mriqc.mriqc_runner import MRIQCWrapper
from .utils import (
    normalize_label,
    parse_mriqc_args,
    setup_logging,
    create_dataset_description,
)
from .nidm_converter import (
    convert_csv_to_nidm,
    convert_mriqc_json_to_csv,
    copy_and_prepare_nidm,
    detect_existing_nidm,
    build_subject_output_path,
    NIDM_FILENAME,
)
from .nidm_converter.csv_to_nidm import check_csv2nidm_available
from .validators import validate_bids_directory, validate_output_directory
from .nidm_converter.data import get_mriqc_dictionary


# Utility functions are now imported from src.utils
# No duplicate definitions needed here


def _cleanup_nidm_intermediates(subject_dir: Path, logger: logging.Logger) -> None:
    """Remove csv2nidm's scratch files from a directory that is about to be zipped.

    csv2nidm copies the target to "<file>.bak" before each in-place append, and
    its create path writes a "<file>.json" term-mapping sidecar. Neither is part
    of the deliverable.
    """
    for pattern in ("*.ttl.bak", "*.ttl.json"):
        for leftover in subject_dir.glob(pattern):
            try:
                leftover.unlink()
                logger.debug(f"Removed NIDM intermediate: {leftover.name}")
            except OSError as e:
                logger.warning(f"Could not remove {leftover}: {e}")


def process_subject(
    subject_id: str,
    bids_dir: Path,
    output_dir: Path,
    subject_dir: Path,
    mriqc_dir: Path,
    session_id: Optional[str],
    nidm_input_dir: Optional[Path],
    skip_mriqc: bool,
    skip_nidm: bool,
    logger: logging.Logger,
) -> bool:
    """
    Process a single subject through the MRIQC → NIDM pipeline.

    Args:
        subject_id: Subject identifier (without 'sub-' prefix)
        bids_dir: BIDS dataset directory
        output_dir: Derivative root (used for staging only)
        subject_dir: Per-subject output dir, <output_dir>/sub-<id>[/ses-<x>]
        mriqc_dir: MRIQC output directory (<subject_dir>/mriqc)
        session_id: Session identifier (without 'ses-' prefix), or None
        nidm_input_dir: Optional NIDM input directory
        skip_mriqc: Skip MRIQC execution (use existing output)
        skip_nidm: Skip NIDM conversion
        logger: Logger instance

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Processing subject: sub-{subject_id}")

    try:
        # Step 1: Detect existing NIDM input
        existing_nidm = detect_existing_nidm(
            subject_id=subject_id,
            nidm_input_dir=nidm_input_dir,
            bids_dir=bids_dir if not nidm_input_dir else None,
            logger=logger
        )

        # Step 2: Find MRIQC outputs
        # MRIQC keeps its own BIDS-derivative structure inside mriqc_dir, so the
        # IQM JSONs live at <mriqc_dir>/sub-<id>/[ses-<x>/]{anat,func}/*.json.
        subject_mriqc_dir = mriqc_dir / f"sub-{subject_id}"

        if not subject_mriqc_dir.exists():
            logger.warning(
                f"No MRIQC output directory found for sub-{subject_id}: "
                f"{subject_mriqc_dir}"
            )
            return False

        # Find all MRIQC IQM JSON files recursively
        # This handles both session and non-session datasets:
        # - Non-session: sub-01/anat/*.json, sub-01/func/*.json
        # - Session: sub-01/ses-01/anat/*.json, sub-01/ses-01/func/*.json
        # IMPORTANT: Filter out non-IQM files like *_timeseries.json which are
        # confounds sidecar files containing metadata, not IQM values
        # Sort for deterministic processing order
        all_json_files = subject_mriqc_dir.rglob("*.json")
        json_files = sorted([
            f for f in all_json_files
            if not f.name.endswith("_timeseries.json")
        ])

        if not json_files:
            logger.warning(f"No MRIQC JSON files found for sub-{subject_id}")
            return False

        logger.info(f"Found {len(json_files)} MRIQC JSON file(s) for sub-{subject_id}")

        if skip_nidm:
            logger.info("Skipping NIDM conversion (--skip-nidm-conversion flag)")
            return True

        # Step 3: Process each MRIQC JSON file.
        # The session is decided by the caller (--session-label), not sniffed from
        # filenames -- it determines the output directory, so it has to be known
        # before MRIQC runs, not after.
        # If the caller did not pin a session, warn when MRIQC produced more than
        # one: everything then lands in a single subject-level nidm.ttl. BABS
        # session-level runs always pass --session-label, so this is the
        # subject-level path only.
        if session_id is None:
            found_sessions = {
                m.group(1)
                for m in (re.search(r"_ses-([a-zA-Z0-9]+)", f.name) for f in json_files)
                if m
            }
            if len(found_sessions) > 1:
                logger.warning(
                    f"sub-{subject_id} has multiple sessions "
                    f"({', '.join(sorted(found_sessions))}) but no --session-label was "
                    "given; all sessions will be merged into one "
                    "subject-level nidm.ttl. "
                    "Pass --session-label to write per-session NIDM instead."
                )

        # NIDM output sits directly in the subject directory, beside the analysis
        # results, and is ALWAYS named nidm.ttl -- subject identity is carried by
        # the directory, not the filename.
        subject_dir.mkdir(parents=True, exist_ok=True)
        subject_ttl_file = subject_dir / NIDM_FILENAME
        logger.debug(f"Target NIDM file: {subject_ttl_file}")

        # Intermediates (per-scan CSVs, csv2nidm .bak/.json sidecars) must not end
        # up inside subject_dir -- that directory is what BABS zips and ships.
        # Stage them in a dot-prefixed sibling at the derivative root instead.
        staging_dir = output_dir / ".nidm_work" / f"sub-{subject_id}"
        if session_id:
            staging_dir = staging_dir / f"ses-{session_id}"
        staging_dir.mkdir(parents=True, exist_ok=True)

        # Get data dictionary path
        dictionary_csv = get_mriqc_dictionary()

        # Step 3a: Copy existing NIDM and prepare augmentation target
        # CRITICAL: Must copy once before loop, not inside loop!
        augmentation_target = None
        if existing_nidm:
            copied_nidm = copy_and_prepare_nidm(
                existing_nidm, subject_dir, logger
            )
            # Rename to canonical name if different
            if copied_nidm != subject_ttl_file:
                copied_nidm.rename(subject_ttl_file)
                logger.info(
                    "Renamed copied NIDM to canonical name: "
                    f"{subject_ttl_file.name}"
                )
            augmentation_target = subject_ttl_file
            logger.info(f"Will augment existing NIDM: {subject_ttl_file}")

        # Track failures to return accurate status
        any_scan_failed = False

        for idx, json_file in enumerate(json_files):
            logger.info(f"Converting {json_file.name} ({idx + 1}/{len(json_files)})")

            # Step 3b: Convert JSON → CSV
            csv_file = staging_dir / f"{json_file.stem}.csv"
            try:
                csv_path, software_csv_path = convert_mriqc_json_to_csv(
                    json_file, csv_file, logger
                )
            except Exception as e:
                logger.error(f"Failed to convert {json_file.name} to CSV: {e}")
                any_scan_failed = True
                continue

            # Step 3c: Convert CSV → NIDM
            # All scans go into the same canonical TTL file
            # First scan creates it, subsequent scans augment it
            existing_nidm_arg = (
                augmentation_target
                if augmentation_target and augmentation_target.exists()
                else None
            )

            try:
                success = convert_csv_to_nidm(
                    csv_file=csv_path,
                    dictionary_csv=dictionary_csv,
                    software_metadata_csv=software_csv_path,
                    output_ttl=subject_ttl_file,
                    existing_nidm=existing_nidm_arg,
                    logger=logger,
                )

                if not success:
                    logger.error(f"Failed to convert {csv_path.name} to NIDM")
                    any_scan_failed = True
                    continue

                # After first successful conversion, set augmentation target
                # so subsequent scans augment the same file
                if not augmentation_target:
                    augmentation_target = subject_ttl_file

            except Exception as e:
                logger.error(f"Error during NIDM conversion: {e}")
                any_scan_failed = True
                continue

        # csv2nidm writes a "<nidm_file>.bak" backup next to its target on every
        # append, and the create path drops a "<out>.json" sidecar. Both are
        # intermediates; left in place they would ship inside the subject's zip.
        _cleanup_nidm_intermediates(subject_dir, logger)

        # Drop the staging tree; it exists only to keep CSVs out of subject_dir.
        shutil.rmtree(staging_dir, ignore_errors=True)

        # Log final output
        if subject_ttl_file.exists():
            size = subject_ttl_file.stat().st_size
            logger.info(
                f"Created consolidated NIDM: {subject_ttl_file} ({size:,} bytes)"
            )

        if any_scan_failed:
            logger.warning(
                f"Some scans failed to process for subject: sub-{subject_id}"
            )
            return False

        logger.info(f"Successfully processed subject: sub-{subject_id}")
        return True

    except Exception as e:
        logger.error(f"Error processing subject sub-{subject_id}: {e}", exc_info=True)
        return False


def main():
    """Main entry point for MRIQC-NIDM BIDSAPP."""
    parser = argparse.ArgumentParser(
        description="MRIQC-NIDM BIDS App - Execute MRIQC and convert to NIDM format",
        epilog="""
MRIQC Arguments:
  Any additional arguments not listed above are passed directly to MRIQC.
  Common MRIQC options include:
    --mem          Maximum memory available (e.g., '16G')
    --nprocs       Maximum number of parallel processes
    --omp-nthreads Maximum number of threads per process
    --no-sub       Disable anonymized metrics submission (default behavior)
    --ica          Run ICA denoising
    --fd-radius    Framewise displacement radius (default: 50mm)

  For full MRIQC options, see: https://mriqc.readthedocs.io/
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required positional arguments (BIDS Apps standard)
    parser.add_argument(
        "bids_dir",
        type=Path,
        help="Path to BIDS dataset directory",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Path to output directory",
    )
    parser.add_argument(
        "analysis_level",
        choices=["participant"],
        help="Analysis level (currently only 'participant' is supported)",
    )

    # Optional arguments
    parser.add_argument(
        "--participant-label",
        nargs="+",
        help="Subject label(s) to process (without 'sub-' prefix)",
    )
    parser.add_argument(
        "--session-label",
        nargs="+",
        help=(
            'Session label(s) to process (without "ses-" prefix, '
            'e.g., "baseline" "followup")'
        ),
    )
    parser.add_argument(
        "--nidm-input-dir",
        type=Path,
        help=(
            "Directory containing existing NIDM files for augmentation. "
            "If not provided, will auto-detect at <BIDS_DIR>/../NIDM/ "
            "(standard convention location)."
        ),
    )
    parser.add_argument(
        "--skip-mriqc",
        action="store_true",
        help="Skip MRIQC execution, use existing output",
    )
    parser.add_argument(
        "--mriqc-output-dir",
        type=Path,
        help="Use existing MRIQC output directory (implies --skip-mriqc)",
    )
    parser.add_argument(
        "--skip-nidm-conversion",
        action="store_true",
        help="Run MRIQC only, skip NIDM conversion",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"MRIQC-NIDM BIDSAPP v{__version__}",
    )

    # Use parse_known_args to capture MRIQC-specific arguments
    args, mriqc_extra_args = parser.parse_known_args()

    # Validate the input before creating anything or starting MRIQC.
    #
    # A bare exists() check is not enough: a directory that exists but has no
    # dataset_description.json is not a BIDS dataset, and MRIQC started against
    # it fails deep inside the container where the cause is buried in MRIQC's
    # traceback. Under BABS that costs a scheduler slot per subject to learn
    # something we can detect here in microseconds.
    if not validate_bids_directory(args.bids_dir):
        return 1

    # Create the output directory through the validator rather than a bare
    # mkdir: it creates with parents=True exactly as before, but turns a
    # read-only parent or an exhausted quota into a reported error instead of
    # an uncaught PermissionError traceback. It also rejects a path that
    # already exists as a file, and one that exists but is not writable --
    # neither of which mkdir(exist_ok=True) would catch.
    if not validate_output_directory(args.output_dir):
        return 1

    # Setup logging
    logger = setup_logging(args.output_dir, args.verbose, __version__)

    # Check for required tools
    if not args.skip_nidm_conversion and not check_csv2nidm_available():
        logger.error(
            "csv2nidm tool not found. Please ensure PyNIDM is installed. "
            "Install with: pip install pynidm"
        )
        return 1

    # Session pinning. BABS session-level jobs always pass --session-label; a
    # subject-level job passes none and everything lands under sub-<id>/.
    session_id = None
    if args.session_label:
        if len(args.session_label) > 1:
            logger.error(
                "Only one --session-label may be given: the session determines the "
                f"output directory. Got: {', '.join(args.session_label)}"
            )
            return 1
        session_id = normalize_label(args.session_label[0], "ses-")

    skip_mriqc = args.skip_mriqc or bool(args.mriqc_output_dir)
    if args.mriqc_output_dir:
        logger.info(f"Using existing MRIQC output: {args.mriqc_output_dir}")

    # Get list of subjects to process
    # Normalize labels to strip 'sub-' prefix if present
    # This makes the code robust to both formats:
    #   --participant-label 0051456
    #   --participant-label sub-0051456
    if args.participant_label:
        subjects = [normalize_label(s, "sub-") for s in args.participant_label]
    else:
        subjects = sorted(
            d.name[4:] for d in args.bids_dir.glob("sub-*") if d.is_dir()
        )

    if not subjects:
        logger.error("No subjects found to process")
        return 1

    # Per-subject output layout: <output_dir>/sub-<id>[/ses-<x>]/ holds nidm.ttl
    # and the mriqc/ results. Resolve both up front so the MRIQC run and the NIDM
    # conversion agree on where things live.
    def _dirs_for(subject_id: str):
        subject_dir = build_subject_output_path(args.output_dir, subject_id, session_id)
        mriqc_dir = (
            Path(args.mriqc_output_dir) if args.mriqc_output_dir
            else subject_dir / "mriqc"
        )
        return subject_dir, mriqc_dir

    # Validate MRIQC directories if skipping execution
    if skip_mriqc:
        missing = [s for s in subjects if not _dirs_for(s)[1].exists()]
        if missing:
            logger.error(
                "MRIQC output directory not found for: "
                + ", ".join(f"sub-{s}" for s in missing)
                + ". This is required when --skip-mriqc or --mriqc-output-dir is used."
            )
            return 1

    logger.info(f"Processing {len(subjects)} subject(s): {', '.join(subjects)}")

    # Run MRIQC if not skipped
    if not skip_mriqc:
        logger.info("Running MRIQC quality control...")

        # Parse extra MRIQC arguments passed through from command line
        mriqc_kwargs = parse_mriqc_args(mriqc_extra_args)
        if mriqc_kwargs:
            logger.info(f"MRIQC extra arguments: {mriqc_kwargs}")

        try:
            mriqc_wrapper = MRIQCWrapper(
                bids_dir=args.bids_dir,
                output_dir=args.output_dir,
            )

            # Process participants with extra MRIQC args. Each subject's MRIQC
            # run targets that subject's own directory, so nothing MRIQC writes
            # at its output root (dataset_description.json, .bidsignore, logs/,
            # the *_T1w.html reports) can collide across subjects.
            for subject_id in subjects:
                _, mriqc_dir = _dirs_for(subject_id)
                logger.info(f"Running MRIQC for sub-{subject_id} → {mriqc_dir}")
                try:
                    mriqc_wrapper.process_participant(
                        subject_id=subject_id,
                        subject_output_dir=mriqc_dir,
                        session_id=session_id,
                        verbose_count=1 if args.verbose else 0,
                        **mriqc_kwargs,
                    )
                except Exception as e:
                    logger.error(f"MRIQC failed for sub-{subject_id}: {e}")
                    continue

            logger.info("MRIQC execution completed")

        except Exception as e:
            logger.error(f"MRIQC execution failed: {e}", exc_info=True)
            return 1

    # Process each subject through NIDM conversion
    success_count = 0
    for subject_id in subjects:
        subject_dir, mriqc_dir = _dirs_for(subject_id)
        if process_subject(
            subject_id=subject_id,
            bids_dir=args.bids_dir,
            output_dir=args.output_dir,
            subject_dir=subject_dir,
            mriqc_dir=mriqc_dir,
            session_id=session_id,
            nidm_input_dir=args.nidm_input_dir,
            skip_mriqc=skip_mriqc,
            skip_nidm=args.skip_nidm_conversion,
            logger=logger,
        ):
            success_count += 1

    # dataset_description.json belongs at the derivative ROOT, beside the sub-*
    # directories -- deliberately outside the per-subject folder BABS zips, so it
    # is written once by whoever assembles the derivative rather than duplicated
    # into (and fought over by) every subject's zip.
    if not args.skip_nidm_conversion:
        create_dataset_description(args.output_dir, version=__version__, logger=logger)

    # Remove the staging root if every subject cleaned up after itself.
    staging_root = args.output_dir / ".nidm_work"
    if staging_root.exists():
        shutil.rmtree(staging_root, ignore_errors=True)

    # Summary
    logger.info(
        f"Processing complete: {success_count}/{len(subjects)} subjects successful"
    )

    if success_count == len(subjects):
        logger.info("All subjects processed successfully")
        return 0
    elif success_count > 0:
        logger.warning("Some subjects failed to process")
        return 1
    else:
        logger.error("All subjects failed to process")
        return 1


if __name__ == "__main__":
    sys.exit(main())
