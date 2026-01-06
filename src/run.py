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
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    build_nidm_output_path,
    build_nidm_filename,
)
from .nidm_converter.csv_to_nidm import check_csv2nidm_available
from .nidm_converter.data import get_mriqc_dictionary


# Utility functions are now imported from src.utils
# No duplicate definitions needed here


def process_subject(
    subject_id: str,
    bids_dir: Path,
    output_dir: Path,
    mriqc_dir: Path,
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
        output_dir: Output directory
        mriqc_dir: MRIQC output directory
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
        # Look for MRIQC JSON files in the MRIQC output directory
        subject_mriqc_dir = mriqc_dir / f"sub-{subject_id}"

        if not subject_mriqc_dir.exists():
            logger.warning(f"No MRIQC output directory found for sub-{subject_id}: {subject_mriqc_dir}")
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

        # Step 3: Process each MRIQC JSON file
        # Extract session info from first JSON file (if present)
        # BABS runs session by session, so all files in one run share the same session
        # Filename pattern: sub-01_ses-01_T1w.json or sub-01_T1w.json
        session_match = re.search(r"_ses-([a-zA-Z0-9]+)", json_files[0].name)
        session_id = session_match.group(1) if session_match else None
        if session_id:
            logger.info(f"Session detected: ses-{session_id}")

        # Build subject/session specific NIDM output directory (standards compliant)
        base_nidm_dir = output_dir / "mriqc-nidm_bidsapp" / "nidm"
        subject_nidm_dir = build_nidm_output_path(base_nidm_dir, subject_id, session_id)
        subject_nidm_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"NIDM output directory: {subject_nidm_dir}")

        # Get data dictionary path
        dictionary_csv = get_mriqc_dictionary()

        # Build canonical TTL filename (ONE file per subject/session)
        # All scans (T1w, bold, etc.) are merged into this single file
        ttl_filename = build_nidm_filename(subject_id, session_id)
        subject_ttl_file = subject_nidm_dir / ttl_filename
        logger.debug(f"Target NIDM file: {subject_ttl_file}")

        # Step 3a: Copy existing NIDM and prepare augmentation target
        # CRITICAL: Must copy once before loop, not inside loop!
        augmentation_target = None
        if existing_nidm:
            copied_nidm = copy_and_prepare_nidm(
                existing_nidm, subject_nidm_dir, logger
            )
            # Rename to canonical name if different
            if copied_nidm != subject_ttl_file:
                copied_nidm.rename(subject_ttl_file)
                logger.info(f"Renamed copied NIDM to canonical name: {subject_ttl_file.name}")
            augmentation_target = subject_ttl_file
            logger.info(f"Will augment existing NIDM: {subject_ttl_file}")

        # Track failures to return accurate status
        any_scan_failed = False

        for idx, json_file in enumerate(json_files):
            logger.info(f"Converting {json_file.name} ({idx + 1}/{len(json_files)})")

            # Step 3b: Convert JSON → CSV
            csv_file = subject_nidm_dir / f"{json_file.stem}.csv"
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
            existing_nidm_arg = augmentation_target if augmentation_target and augmentation_target.exists() else None

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

        # Log final output
        if subject_ttl_file.exists():
            logger.info(f"Created consolidated NIDM: {subject_ttl_file}")

        if any_scan_failed:
            logger.warning(f"Some scans failed to process for subject: sub-{subject_id}")
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
        help='Session label(s) to process (without "ses-" prefix, e.g., "baseline" "followup")',
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

    # Validate paths
    if not args.bids_dir.exists():
        print(f"Error: BIDS directory not found: {args.bids_dir}", file=sys.stderr)
        return 1

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    logger = setup_logging(args.output_dir, args.verbose, __version__)

    # Check for required tools
    if not args.skip_nidm_conversion and not check_csv2nidm_available():
        logger.error(
            "csv2nidm tool not found. Please ensure PyNIDM is installed. "
            "Install with: pip install pynidm"
        )
        return 1

    # Determine MRIQC output directory
    if args.mriqc_output_dir:
        mriqc_dir = args.mriqc_output_dir
        skip_mriqc = True
        logger.info(f"Using existing MRIQC output: {mriqc_dir}")
    else:
        mriqc_dir = args.output_dir / "mriqc-nidm_bidsapp" / "mriqc"
        skip_mriqc = args.skip_mriqc

    # Validate MRIQC directory if skipping execution
    if skip_mriqc and not mriqc_dir.exists():
        logger.error(
            f"MRIQC output directory not found: {mriqc_dir}. "
            "This is required when --skip-mriqc or --mriqc-output-dir is used."
        )
        return 1

    # Get list of subjects to process
    # Normalize labels to strip 'sub-' prefix if present
    # This makes the code robust to both formats:
    #   --participant-label 0051456
    #   --participant-label sub-0051456
    if args.participant_label:
        subjects = [normalize_label(s, "sub-") for s in args.participant_label]
    else:
        # Find all subjects in MRIQC output (if exists) or BIDS directory
        if mriqc_dir.exists():
            subjects = [d.name[4:] for d in mriqc_dir.glob("sub-*") if d.is_dir()]
        else:
            subjects = [d.name[4:] for d in args.bids_dir.glob("sub-*") if d.is_dir()]

    if not subjects:
        logger.error("No subjects found to process")
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

            # Process participants with extra MRIQC args
            for subject_id in subjects:
                logger.info(f"Running MRIQC for sub-{subject_id}")
                try:
                    mriqc_wrapper.process_participant(
                        subject_id=subject_id,
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
        if process_subject(
            subject_id=subject_id,
            bids_dir=args.bids_dir,
            output_dir=args.output_dir,
            mriqc_dir=mriqc_dir,
            nidm_input_dir=args.nidm_input_dir,
            skip_mriqc=skip_mriqc,
            skip_nidm=args.skip_nidm_conversion,
            logger=logger,
        ):
            success_count += 1

    # Create dataset description
    if not args.skip_nidm_conversion:
        create_dataset_description(args.output_dir, version=__version__, logger=logger)

    # Summary
    logger.info(f"Processing complete: {success_count}/{len(subjects)} subjects successful")

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
