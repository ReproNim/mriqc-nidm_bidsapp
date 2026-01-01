#!/usr/bin/env python3
"""
Tests for session handling in run.py

This module tests that the MRIQC JSON discovery correctly handles both:
1. Non-session datasets: sub-01/anat/*.json, sub-01/func/*.json
2. Multi-session datasets: sub-01/ses-01/anat/*.json, sub-01/ses-02/anat/*.json

Critical for P1 bug fix: ensuring multi-session datasets are processed correctly.
"""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mriqc.run import process_subject


@pytest.fixture
def logger():
    """Create a test logger."""
    return logging.getLogger("test")


@pytest.fixture
def mock_bids_dir(tmp_path):
    """Create a mock BIDS directory."""
    bids_dir = tmp_path / "BIDS"
    bids_dir.mkdir()
    return bids_dir


@pytest.fixture
def mock_output_dir(tmp_path):
    """Create a mock output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


def create_mriqc_json(file_path: Path, subject_id: str, session_id: str = None):
    """Helper to create a mock MRIQC JSON file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "bids_meta": {
            "subject_id": subject_id,
        },
        "provenance": {
            "software": "MRIQC",
            "version": "23.0.0",
        },
        "snr": 10.5,
        "cnr": 8.2,
    }

    if session_id:
        data["bids_meta"]["session_id"] = session_id

    with open(file_path, "w") as f:
        json.dump(data, f)


class TestSessionHandling:
    """Test MRIQC JSON discovery with session handling."""

    def test_non_session_dataset_single_scan(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test finding MRIQC JSONs in non-session dataset (single scan)."""
        # Setup: non-session structure
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"

        # Create MRIQC output: sub-01/anat/sub-01_T1w.json
        json_file = mriqc_dir / f"sub-{subject_id}" / "anat" / f"sub-{subject_id}_T1w.json"
        create_mriqc_json(json_file, subject_id)

        # Mock conversion functions to test only JSON discovery
        with patch("mriqc.run.convert_mriqc_json_to_csv") as mock_json2csv, \
             patch("mriqc.run.convert_csv_to_nidm") as mock_csv2nidm, \
             patch("mriqc.run.get_mriqc_dictionary") as mock_dict:

            mock_json2csv.return_value = (Path("dummy.csv"), Path("dummy_software.csv"))
            mock_csv2nidm.return_value = True
            mock_dict.return_value = Path("dummy_dict.csv")

            result = process_subject(
                subject_id=subject_id,
                bids_dir=mock_bids_dir,
                output_dir=mock_output_dir,
                mriqc_dir=mriqc_dir,
                nidm_input_dir=None,
                skip_mriqc=True,
                skip_nidm=False,
                logger=logger,
            )

            # Should succeed and find 1 JSON file
            assert result is True
            assert mock_json2csv.call_count == 1

    def test_non_session_dataset_multiple_scans(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test finding MRIQC JSONs in non-session dataset (multiple scans)."""
        # Setup: non-session structure with multiple datatypes
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"

        # Create MRIQC outputs in different datatypes
        anat_file = mriqc_dir / f"sub-{subject_id}" / "anat" / f"sub-{subject_id}_T1w.json"
        func_file = mriqc_dir / f"sub-{subject_id}" / "func" / f"sub-{subject_id}_task-rest_bold.json"
        create_mriqc_json(anat_file, subject_id)
        create_mriqc_json(func_file, subject_id)

        with patch("mriqc.run.convert_mriqc_json_to_csv") as mock_json2csv, \
             patch("mriqc.run.convert_csv_to_nidm") as mock_csv2nidm, \
             patch("mriqc.run.get_mriqc_dictionary") as mock_dict:

            mock_json2csv.return_value = (Path("dummy.csv"), Path("dummy_software.csv"))
            mock_csv2nidm.return_value = True
            mock_dict.return_value = Path("dummy_dict.csv")

            result = process_subject(
                subject_id=subject_id,
                bids_dir=mock_bids_dir,
                output_dir=mock_output_dir,
                mriqc_dir=mriqc_dir,
                nidm_input_dir=None,
                skip_mriqc=True,
                skip_nidm=False,
                logger=logger,
            )

            # Should succeed and find 2 JSON files
            assert result is True
            assert mock_json2csv.call_count == 2

    def test_session_dataset_single_session(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test finding MRIQC JSONs in multi-session dataset (single session)."""
        # Setup: session structure
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"
        session_id = "01"

        # Create MRIQC output: sub-01/ses-01/anat/sub-01_ses-01_T1w.json
        json_file = (
            mriqc_dir / f"sub-{subject_id}" / f"ses-{session_id}" /
            "anat" / f"sub-{subject_id}_ses-{session_id}_T1w.json"
        )
        create_mriqc_json(json_file, subject_id, session_id)

        with patch("mriqc.run.convert_mriqc_json_to_csv") as mock_json2csv, \
             patch("mriqc.run.convert_csv_to_nidm") as mock_csv2nidm, \
             patch("mriqc.run.get_mriqc_dictionary") as mock_dict:

            mock_json2csv.return_value = (Path("dummy.csv"), Path("dummy_software.csv"))
            mock_csv2nidm.return_value = True
            mock_dict.return_value = Path("dummy_dict.csv")

            result = process_subject(
                subject_id=subject_id,
                bids_dir=mock_bids_dir,
                output_dir=mock_output_dir,
                mriqc_dir=mriqc_dir,
                nidm_input_dir=None,
                skip_mriqc=True,
                skip_nidm=False,
                logger=logger,
            )

            # Should succeed and find 1 JSON file
            assert result is True
            assert mock_json2csv.call_count == 1

    def test_session_dataset_multiple_sessions(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test finding MRIQC JSONs in multi-session dataset (multiple sessions)."""
        # Setup: multiple sessions
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"

        # Create MRIQC outputs for multiple sessions
        for session_id in ["01", "02", "03"]:
            json_file = (
                mriqc_dir / f"sub-{subject_id}" / f"ses-{session_id}" /
                "anat" / f"sub-{subject_id}_ses-{session_id}_T1w.json"
            )
            create_mriqc_json(json_file, subject_id, session_id)

        with patch("mriqc.run.convert_mriqc_json_to_csv") as mock_json2csv, \
             patch("mriqc.run.convert_csv_to_nidm") as mock_csv2nidm, \
             patch("mriqc.run.get_mriqc_dictionary") as mock_dict:

            mock_json2csv.return_value = (Path("dummy.csv"), Path("dummy_software.csv"))
            mock_csv2nidm.return_value = True
            mock_dict.return_value = Path("dummy_dict.csv")

            result = process_subject(
                subject_id=subject_id,
                bids_dir=mock_bids_dir,
                output_dir=mock_output_dir,
                mriqc_dir=mriqc_dir,
                nidm_input_dir=None,
                skip_mriqc=True,
                skip_nidm=False,
                logger=logger,
            )

            # Should succeed and find 3 JSON files (one per session)
            assert result is True
            assert mock_json2csv.call_count == 3

    def test_session_dataset_multiple_sessions_multiple_datatypes(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test finding MRIQC JSONs with sessions and multiple datatypes."""
        # Setup: multiple sessions with multiple datatypes each
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"

        # Create MRIQC outputs for sessions with different datatypes
        for session_id in ["01", "02"]:
            # Anatomical scan
            anat_file = (
                mriqc_dir / f"sub-{subject_id}" / f"ses-{session_id}" /
                "anat" / f"sub-{subject_id}_ses-{session_id}_T1w.json"
            )
            create_mriqc_json(anat_file, subject_id, session_id)

            # Functional scan
            func_file = (
                mriqc_dir / f"sub-{subject_id}" / f"ses-{session_id}" /
                "func" / f"sub-{subject_id}_ses-{session_id}_task-rest_bold.json"
            )
            create_mriqc_json(func_file, subject_id, session_id)

        with patch("mriqc.run.convert_mriqc_json_to_csv") as mock_json2csv, \
             patch("mriqc.run.convert_csv_to_nidm") as mock_csv2nidm, \
             patch("mriqc.run.get_mriqc_dictionary") as mock_dict:

            mock_json2csv.return_value = (Path("dummy.csv"), Path("dummy_software.csv"))
            mock_csv2nidm.return_value = True
            mock_dict.return_value = Path("dummy_dict.csv")

            result = process_subject(
                subject_id=subject_id,
                bids_dir=mock_bids_dir,
                output_dir=mock_output_dir,
                mriqc_dir=mriqc_dir,
                nidm_input_dir=None,
                skip_mriqc=True,
                skip_nidm=False,
                logger=logger,
            )

            # Should succeed and find 4 JSON files (2 sessions × 2 datatypes)
            assert result is True
            assert mock_json2csv.call_count == 4

    def test_no_json_files_found(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test behavior when no MRIQC JSON files are found."""
        # Setup: empty MRIQC directory structure
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"

        # Create empty directory structure (no JSON files)
        (mriqc_dir / f"sub-{subject_id}" / "anat").mkdir(parents=True)

        result = process_subject(
            subject_id=subject_id,
            bids_dir=mock_bids_dir,
            output_dir=mock_output_dir,
            mriqc_dir=mriqc_dir,
            nidm_input_dir=None,
            skip_mriqc=True,
            skip_nidm=False,
            logger=logger,
        )

        # Should fail when no JSON files are found
        assert result is False

    def test_no_mriqc_directory(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test behavior when MRIQC output directory doesn't exist."""
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "99"  # Subject that doesn't exist

        result = process_subject(
            subject_id=subject_id,
            bids_dir=mock_bids_dir,
            output_dir=mock_output_dir,
            mriqc_dir=mriqc_dir,
            nidm_input_dir=None,
            skip_mriqc=True,
            skip_nidm=False,
            logger=logger,
        )

        # Should fail when subject directory doesn't exist
        assert result is False

    def test_skip_nidm_conversion_with_sessions(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test that JSON discovery works even when skipping NIDM conversion."""
        # Setup: session structure
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"
        session_id = "01"

        # Create MRIQC output
        json_file = (
            mriqc_dir / f"sub-{subject_id}" / f"ses-{session_id}" /
            "anat" / f"sub-{subject_id}_ses-{session_id}_T1w.json"
        )
        create_mriqc_json(json_file, subject_id, session_id)

        result = process_subject(
            subject_id=subject_id,
            bids_dir=mock_bids_dir,
            output_dir=mock_output_dir,
            mriqc_dir=mriqc_dir,
            nidm_input_dir=None,
            skip_mriqc=True,
            skip_nidm=True,  # Skip NIDM conversion
            logger=logger,
        )

        # Should succeed - JSON discovery happens before NIDM conversion
        assert result is True


class TestSessionHandlingDeterminism:
    """Test that file processing order is deterministic."""

    def test_files_processed_in_sorted_order(
        self, mock_bids_dir, mock_output_dir, logger, tmp_path
    ):
        """Test that JSON files are processed in sorted (deterministic) order."""
        mriqc_dir = tmp_path / "mriqc"
        subject_id = "01"

        # Create files in non-alphabetical directory order (ses-03, ses-01, ses-02)
        # to ensure sorting happens correctly
        session_ids = ["03", "01", "02"]

        for session_id in session_ids:
            json_file = (
                mriqc_dir / f"sub-{subject_id}" / f"ses-{session_id}" /
                "anat" / f"sub-{subject_id}_ses-{session_id}_T1w.json"
            )
            create_mriqc_json(json_file, subject_id, session_id)

        with patch("mriqc.run.convert_mriqc_json_to_csv") as mock_json2csv, \
             patch("mriqc.run.convert_csv_to_nidm") as mock_csv2nidm, \
             patch("mriqc.run.get_mriqc_dictionary") as mock_dict:

            mock_json2csv.return_value = (Path("dummy.csv"), Path("dummy_software.csv"))
            mock_csv2nidm.return_value = True
            mock_dict.return_value = Path("dummy_dict.csv")

            result = process_subject(
                subject_id=subject_id,
                bids_dir=mock_bids_dir,
                output_dir=mock_output_dir,
                mriqc_dir=mriqc_dir,
                nidm_input_dir=None,
                skip_mriqc=True,
                skip_nidm=False,
                logger=logger,
            )

            assert result is True

            # Verify files were processed in sorted order
            call_args = [call[0][0] for call in mock_json2csv.call_args_list]
            call_filenames = [arg.name for arg in call_args]

            # Should be sorted alphabetically
            assert call_filenames == sorted(call_filenames)
            assert call_filenames == [
                "sub-01_ses-01_T1w.json",
                "sub-01_ses-02_T1w.json",
                "sub-01_ses-03_T1w.json",
            ]
