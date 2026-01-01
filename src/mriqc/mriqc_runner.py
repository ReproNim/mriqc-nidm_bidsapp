#!/usr/bin/env python3
"""
MRIQC Wrapper for BIDS App

This module provides a wrapper around MRIQC to execute quality control
analysis on BIDS datasets and manage MRIQC outputs for subsequent NIDM
conversion.
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bids import BIDSLayout, __version__ as bids_version

from . import __version__

# Configure logging
logger = logging.getLogger("mriqc-nidm.wrapper")


class MRIQCWrapper:
    """Wrapper for MRIQC quality control tool."""

    # MRIQC output datatypes to search
    MRIQC_DATATYPES = ["anat", "func", "dwi"]

    def __init__(
        self,
        bids_dir: Path,
        output_dir: Path,
        work_dir: Optional[Path] = None,
        mriqc_version: Optional[str] = None,
    ):
        """
        Initialize MRIQC wrapper.

        Parameters
        ----------
        bids_dir : Path
            Path to BIDS dataset directory
        output_dir : Path
            Path to output derivatives directory
        work_dir : Path, optional
            Path to working directory for intermediate files
        mriqc_version : str, optional
            Specific MRIQC version to use (if applicable)
        """
        self.bids_dir = Path(bids_dir)
        self.output_dir = Path(output_dir)
        self.mriqc_dir = self.output_dir / "mriqc-nidm_bidsapp" / "mriqc"
        self.work_dir = Path(work_dir) if work_dir else self.output_dir / "work"

        # Track processing results
        self.results = {"success": [], "failure": [], "skipped": []}

        # Ensure output directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mriqc_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Check MRIQC installation
        self.mriqc_version = mriqc_version or self._get_mriqc_version()
        logger.info(f"Using MRIQC version: {self.mriqc_version}")

    def _get_mriqc_version(self) -> str:
        """
        Get installed MRIQC version.

        Returns
        -------
        str
            MRIQC version string, or "unknown" if not available
        """
        try:
            result = subprocess.run(
                ["mriqc", "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                # Parse version from output (e.g., "MRIQC v0.16.1")
                version = result.stdout.strip().split()[-1]
                return version.lstrip("v")
            else:
                logger.warning("Unable to determine MRIQC version")
                return "unknown"
        except FileNotFoundError:
            logger.error("MRIQC not found in PATH")
            raise RuntimeError(
                "MRIQC is not installed or not available in PATH. "
                "Please ensure MRIQC is properly installed."
            )

    def _create_mriqc_command(
        self,
        output_dir: Path,
        subject_id: Optional[str] = None,
        session_id: Optional[str] = None,
        modalities: Optional[List[str]] = None,
        nprocs: Optional[int] = None,
        mem_gb: Optional[int] = None,
        fd_radius: Optional[float] = None,
        no_sub: bool = True,
        verbose_count: int = 0,
        **kwargs,
    ) -> List[str]:
        """
        Create MRIQC command with specified parameters.

        Parameters
        ----------
        output_dir : Path
            Subject-specific output directory for MRIQC results
        subject_id : str, optional
            Subject ID to process (without 'sub-' prefix)
        session_id : str, optional
            Session ID to process (without 'ses-' prefix)
        modalities : list of str, optional
            List of modalities to process (e.g., ['T1w', 'bold'])
        nprocs : int, optional
            Number of parallel processes
        mem_gb : int, optional
            Memory limit in GB
        fd_radius : float, optional
            Radius for framewise displacement calculation (default: 50mm)
        no_sub : bool
            Disable submission of anonymized quality metrics (default: True)
        verbose_count : int
            Verbosity level (0-2, adds -v flags)
        **kwargs
            Additional MRIQC arguments

        Returns
        -------
        list
            Command list for subprocess
        """
        cmd = ["mriqc", str(self.bids_dir), str(output_dir), "participant"]

        # Working directory
        cmd.extend(["-w", str(self.work_dir)])

        # Subject and session filters
        if subject_id:
            cmd.extend(["--participant-label", subject_id])

        if session_id:
            cmd.extend(["--session-id", session_id])

        # Modality filters
        if modalities:
            for modality in modalities:
                cmd.extend(["-m", modality])

        # Performance parameters
        if nprocs is not None:
            cmd.extend(["--nprocs", str(nprocs)])

        if mem_gb is not None:
            cmd.extend(["--mem", str(mem_gb)])

        # FD calculation radius (MRIQC default is 50mm)
        if fd_radius is not None:
            cmd.extend(["--fd_radius", str(fd_radius)])

        # Disable metrics submission
        if no_sub:
            cmd.append("--no-sub")

        # Verbosity
        for _ in range(verbose_count):
            cmd.append("-v")

        # Additional kwargs (handles passthrough arguments from CLI)
        for key, value in kwargs.items():
            # Special handling for 'mem' (CLI uses --mem, wrapper uses mem_gb)
            if key == "mem":
                if mem_gb is None:
                    # Only use mem kwarg if mem_gb was not set
                    cmd.extend(["--mem", str(value)])
                # else: Skip - mem_gb parameter takes precedence
                continue
            elif value is True:
                cmd.append(f"--{key.replace('_', '-')}")
            elif value is not False and value is not None:
                cmd.extend([f"--{key.replace('_', '-')}", str(value)])

        return cmd

    def _get_participant_identifier(
        self, subject_id: str, session_id: Optional[str] = None
    ) -> str:
        """
        Construct participant identifier string.

        Parameters
        ----------
        subject_id : str
            Subject ID (without 'sub-' prefix)
        session_id : str, optional
            Session ID (without 'ses-' prefix)

        Returns
        -------
        str
            Formatted participant identifier (e.g., 'sub-01' or 'sub-01_ses-01')
        """
        identifier = f"sub-{subject_id}"
        if session_id:
            identifier += f"_ses-{session_id}"
        return identifier

    def process_participant(
        self,
        subject_id: str,
        subject_output_dir: Optional[Path] = None,
        session_id: Optional[str] = None,
        modalities: Optional[List[str]] = None,
        skip_existing: bool = True,
        **kwargs,
    ) -> bool:
        """
        Process a single participant with MRIQC.

        Parameters
        ----------
        subject_id : str
            Subject ID (without 'sub-' prefix)
        subject_output_dir : Path, optional
            Subject-specific output directory (e.g., output_dir/sub-01/mriqc/)
            If None, uses default mriqc_dir
        session_id : str, optional
            Session ID (without 'ses-' prefix)
        modalities : list of str, optional
            List of modalities to process (e.g., ['T1w', 'bold'])
        skip_existing : bool
            Skip processing if MRIQC output already exists
        **kwargs
            Additional arguments passed to MRIQC

        Returns
        -------
        bool
            True if processing was successful, False otherwise
        """
        participant_id = self._get_participant_identifier(subject_id, session_id)

        # Use subject-specific output directory if provided, otherwise use default
        output_dir = subject_output_dir if subject_output_dir else self.mriqc_dir
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"Processing subject: {participant_id} → {output_dir}"
        )

        try:
            # Check if already processed
            if skip_existing:
                existing_outputs = self.find_mriqc_outputs(
                    subject_id=subject_id,
                    session_id=session_id,
                    search_dir=output_dir
                )
                if existing_outputs:
                    logger.info(f"{participant_id} already processed. Skipping...")
                    self.results["skipped"].append(participant_id)
                    return True

            # Create MRIQC command
            cmd = self._create_mriqc_command(
                output_dir=output_dir,
                subject_id=subject_id,
                session_id=session_id,
                modalities=modalities,
                **kwargs,
            )

            logger.info(f"Running command: {' '.join(cmd)}")

            # Execute MRIQC
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                logger.error(f"MRIQC failed for {participant_id}: {result.stderr}")
                self.results["failure"].append(participant_id)
                return False

            # Verify outputs were created
            outputs = self.find_mriqc_outputs(
                subject_id=subject_id,
                session_id=session_id,
                search_dir=output_dir
            )
            if not outputs:
                logger.warning(
                    f"MRIQC completed but no outputs found for {participant_id}"
                )
                self.results["failure"].append(participant_id)
                return False

            self.results["success"].append(participant_id)
            logger.info(f"Successfully processed {participant_id}")
            return True

        except (subprocess.SubprocessError, OSError, ValueError) as e:
            logger.error(f"Error processing {participant_id}: {str(e)}")
            self.results["failure"].append(participant_id)
            return False

    def process_all_participants(
        self,
        participant_labels: Optional[List[str]] = None,
        session_ids: Optional[List[str]] = None,
        modalities: Optional[List[str]] = None,
        skip_existing: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Process multiple participants with MRIQC.

        Parameters
        ----------
        participant_labels : list of str, optional
            List of subject IDs to process (without 'sub-' prefix)
            If None, processes all subjects in BIDS dataset
        session_ids : list of str, optional
            List of session IDs to process (without 'ses-' prefix)
        modalities : list of str, optional
            List of modalities to process (e.g., ['T1w', 'bold'])
        skip_existing : bool
            Skip processing if MRIQC output already exists
        **kwargs
            Additional arguments passed to MRIQC

        Returns
        -------
        dict
            Summary of processing results
        """
        # Discover subjects if not specified
        if participant_labels is None:
            try:
                layout = BIDSLayout(self.bids_dir, validate=False)
                participant_labels = layout.get_subjects()
                logger.info(
                    f"Found {len(participant_labels)} subjects in BIDS dataset"
                )
            except Exception as e:
                logger.error(f"Failed to read BIDS dataset: {str(e)}")
                return self.get_processing_summary()

        if not participant_labels:
            logger.warning("No participants to process")
            return self.get_processing_summary()

        # Process each subject
        for subject_id in participant_labels:
            # Handle session-specific processing
            if session_ids:
                for session_id in session_ids:
                    self.process_participant(
                        subject_id=subject_id,
                        session_id=session_id,
                        modalities=modalities,
                        skip_existing=skip_existing,
                        **kwargs,
                    )
            else:
                self.process_participant(
                    subject_id=subject_id,
                    modalities=modalities,
                    skip_existing=skip_existing,
                    **kwargs,
                )

        return self.get_processing_summary()

    def find_mriqc_outputs(
        self,
        subject_id: str,
        session_id: Optional[str] = None,
        search_dir: Optional[Path] = None,
        modality: Optional[str] = None,
    ) -> List[Path]:
        """
        Find MRIQC output JSON files for a subject.

        Parameters
        ----------
        subject_id : str
            Subject ID (without 'sub-' prefix)
        session_id : str, optional
            Session ID (without 'ses-' prefix)
        search_dir : Path, optional
            Directory to search in (if None, uses self.mriqc_dir)
        modality : str, optional
            Modality to filter (e.g., 'T1w', 'bold')

        Returns
        -------
        list of Path
            List of MRIQC JSON output files
        """
        outputs = []

        # MRIQC output pattern: sub-XX[_ses-YY][_task-ZZ]_<modality>.json
        pattern = f"sub-{subject_id}"
        if session_id:
            pattern += f"_ses-{session_id}"

        # Use provided search_dir or default to mriqc_dir
        base_dir = search_dir if search_dir else self.mriqc_dir

        # Search in MRIQC output directory
        # Note: In subject-centric mode, search_dir is already subject-specific (e.g., sub-01/mriqc/)
        # In legacy mode, we need to append sub-01
        if "sub-" not in str(base_dir):
            subject_dir = base_dir / f"sub-{subject_id}"
        else:
            subject_dir = base_dir

        if session_id and "ses-" not in str(subject_dir):
            subject_dir = subject_dir / f"ses-{session_id}"

        if not subject_dir.exists():
            return outputs

        # Look in MRIQC output directories
        for datatype in self.MRIQC_DATATYPES:
            datatype_dir = subject_dir / datatype
            if not datatype_dir.exists():
                continue

            # Find JSON files matching pattern
            for json_file in datatype_dir.glob(f"{pattern}*.json"):
                if modality:
                    # BIDS suffix is the modality (last part before extension)
                    # e.g., "sub-01_T1w.json" -> suffix is "T1w"
                    suffix = json_file.stem.split("_")[-1]
                    if modality == suffix:
                        outputs.append(json_file)
                else:
                    outputs.append(json_file)

        return sorted(outputs)

    def get_processing_summary(self) -> Dict[str, Any]:
        """
        Get summary of processing results.

        Returns
        -------
        dict
            Dictionary containing processing statistics
        """
        return {
            "total": len(self.results["success"])
            + len(self.results["failure"])
            + len(self.results["skipped"]),
            "success": len(self.results["success"]),
            "failure": len(self.results["failure"]),
            "skipped": len(self.results["skipped"]),
            "success_list": self.results["success"],
            "failure_list": self.results["failure"],
            "skipped_list": self.results["skipped"],
        }

    def save_processing_summary(self, summary: Optional[Dict] = None) -> Path:
        """
        Save processing summary to JSON file.

        Parameters
        ----------
        summary : dict, optional
            Summary dictionary (if None, generates from current results)

        Returns
        -------
        Path
            Path to saved summary file
        """
        if summary is None:
            summary = self.get_processing_summary()

        summary["timestamp"] = datetime.now().isoformat()
        summary["mriqc_version"] = self.mriqc_version

        output_path = self.mriqc_dir / "processing_summary.json"
        with open(output_path, "w") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Processing summary saved to {output_path}")
        return output_path

    def create_dataset_description(self) -> Path:
        """
        Create dataset_description.json for MRIQC derivatives.

        Returns
        -------
        Path
            Path to created dataset_description.json
        """
        desc_file = self.mriqc_dir / "dataset_description.json"

        if desc_file.exists():
            logger.info(f"dataset_description.json already exists: {desc_file}")
            return desc_file

        description = {
            "Name": "MRIQC - MRI Quality Control",
            "BIDSVersion": bids_version,
            "DatasetType": "derivative",
            "GeneratedBy": [
                {
                    "Name": "MRIQC",
                    "Version": self.mriqc_version,
                    "Description": "MRI Quality Control tool for BIDS datasets",
                    "CodeURL": "https://github.com/nipreps/mriqc",
                },
                {
                    "Name": "mriqc-nidm",
                    "Version": __version__,
                    "Description": "MRIQC to NIDM BIDS App",
                },
            ],
            "HowToAcknowledge": "Please cite MRIQC (https://doi.org/10.1371/journal.pone.0184661)",
        }

        with open(desc_file, "w") as f:
            json.dump(description, f, indent=2)

        logger.info(f"Created dataset_description.json: {desc_file}")
        return desc_file
