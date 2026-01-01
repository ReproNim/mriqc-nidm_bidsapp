#!/usr/bin/env python3
"""
Unit tests for MRIQC runner module.

These tests verify the MRIQC runner functionality including:
- Initialization and configuration
- Command generation
- Subject processing
- Output discovery
- Result tracking
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from mriqc.mriqc_runner import MRIQCWrapper


@pytest.fixture
def test_dirs(tmp_path):
    """Create test directory structure."""
    bids_dir = tmp_path / "bids"
    output_dir = tmp_path / "output"
    work_dir = tmp_path / "work"

    # Create BIDS dataset structure
    bids_dir.mkdir(parents=True)
    (bids_dir / "dataset_description.json").write_text(
        json.dumps({"Name": "Test Dataset", "BIDSVersion": "1.4.0"})
    )

    # Create subject directories
    for sub in ["01", "02"]:
        sub_dir = bids_dir / f"sub-{sub}" / "anat"
        sub_dir.mkdir(parents=True)
        (sub_dir / f"sub-{sub}_T1w.nii.gz").touch()

    return {
        "bids_dir": bids_dir,
        "output_dir": output_dir,
        "work_dir": work_dir,
    }


@pytest.fixture
def mock_mriqc_version():
    """Mock MRIQC version check."""
    with patch("mriqc.mriqc_runner.subprocess.run") as mock_run:
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "MRIQC v0.16.1\n"
        mock_run.return_value = mock_result
        yield mock_run


class TestMRIQCWrapperInit:
    """Test MRIQC wrapper initialization."""

    def test_init_creates_directories(self, test_dirs, mock_mriqc_version):
        """Test that initialization creates required directories."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
            work_dir=test_dirs["work_dir"],
        )

        assert wrapper.output_dir.exists()
        assert wrapper.mriqc_dir.exists()
        assert wrapper.work_dir.exists()

    def test_init_sets_paths(self, test_dirs, mock_mriqc_version):
        """Test that initialization sets correct paths."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        assert wrapper.bids_dir == test_dirs["bids_dir"]
        assert wrapper.output_dir == test_dirs["output_dir"]
        assert wrapper.mriqc_dir == test_dirs["output_dir"] / "mriqc-nidm_bidsapp" / "mriqc"
        assert wrapper.work_dir == test_dirs["output_dir"] / "work"

    def test_init_tracks_results(self, test_dirs, mock_mriqc_version):
        """Test that initialization creates results tracking."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        assert "success" in wrapper.results
        assert "failure" in wrapper.results
        assert "skipped" in wrapper.results
        assert isinstance(wrapper.results["success"], list)

    def test_init_checks_mriqc_version(self, test_dirs, mock_mriqc_version):
        """Test that initialization checks MRIQC version."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        assert wrapper.mriqc_version == "0.16.1"
        mock_mriqc_version.assert_called_once()

    def test_init_handles_missing_mriqc(self, test_dirs):
        """Test that initialization raises error if MRIQC not found."""
        with patch("mriqc.mriqc_runner.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="MRIQC is not installed"):
                MRIQCWrapper(
                    bids_dir=test_dirs["bids_dir"],
                    output_dir=test_dirs["output_dir"],
                )


class TestMRIQCWrapperCommands:
    """Test MRIQC command generation."""

    def test_create_basic_command(self, test_dirs, mock_mriqc_version):
        """Test basic MRIQC command generation."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir)

        assert cmd[0] == "mriqc"
        assert str(test_dirs["bids_dir"]) in cmd
        assert str(wrapper.mriqc_dir) in cmd
        assert "participant" in cmd

    def test_create_command_with_subject(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with subject filter."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir, subject_id="01")

        assert "--participant-label" in cmd
        assert "01" in cmd

    def test_create_command_with_session(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with session filter."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir, subject_id="01", session_id="01")

        assert "--session-id" in cmd
        assert "01" in cmd

    def test_create_command_with_modalities(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with modality filters."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir, modalities=["T1w", "bold"])

        assert cmd.count("-m") == 2
        assert "T1w" in cmd
        assert "bold" in cmd

    def test_create_command_with_performance_params(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with performance parameters."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir, nprocs=4, mem_gb=16)

        assert "--nprocs" in cmd
        assert "4" in cmd
        assert "--mem" in cmd
        assert "16" in cmd

    def test_create_command_with_no_sub(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with --no-sub flag."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir, no_sub=True)

        assert "--no-sub" in cmd

    def test_create_command_with_verbose(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with verbose flags."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir, verbose_count=2)

        assert cmd.count("-v") == 2

    def test_create_command_with_fd_radius(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with FD radius parameter."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        cmd = wrapper._create_mriqc_command(output_dir=wrapper.mriqc_dir, fd_radius=45.0)

        assert "--fd_radius" in cmd
        assert "45.0" in cmd

    def test_create_command_with_passthrough_kwargs(self, test_dirs, mock_mriqc_version):
        """Test MRIQC command with passthrough arguments via kwargs."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Test passthrough args like those from BABS config
        cmd = wrapper._create_mriqc_command(
            output_dir=wrapper.mriqc_dir,
            subject_id="01",
            mem="16G",  # Passthrough via kwargs
            omp_nthreads=8,  # Passthrough via kwargs
            ica=True,  # Boolean flag
        )

        cmd_str = " ".join(cmd)

        # Check mem is passed through
        assert "--mem" in cmd
        assert "16G" in cmd

        # Check omp-nthreads is passed (underscore converted to hyphen)
        assert "--omp-nthreads" in cmd
        assert "8" in cmd

        # Check boolean flag
        assert "--ica" in cmd

    def test_create_command_mem_via_kwargs_not_duplicate(self, test_dirs, mock_mriqc_version):
        """Test that mem via kwargs doesn't duplicate if mem_gb is also set."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # If both mem_gb (explicit param) and mem (kwargs) are set,
        # mem_gb takes precedence and mem should be skipped
        cmd = wrapper._create_mriqc_command(
            output_dir=wrapper.mriqc_dir,
            mem_gb=32,  # Explicit parameter
            mem="16G",  # Via kwargs - should be ignored
        )

        # Count occurrences of --mem
        mem_count = cmd.count("--mem")
        assert mem_count == 1, f"Expected 1 --mem, got {mem_count}"

        # Should use mem_gb value, not mem kwarg
        assert "32" in cmd


class TestMRIQCWrapperProcessing:
    """Test MRIQC processing functionality."""

    def test_process_participant_success(self, test_dirs, mock_mriqc_version):
        """Test successful participant processing."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create mock output file first (before mocking subprocess)
        output_file = (
            wrapper.mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json"
        )
        output_file.parent.mkdir(parents=True)
        output_file.write_text("{}")

        # Mock subprocess.run
        with patch("mriqc.mriqc_runner.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "Success"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            result = wrapper.process_participant(subject_id="01", skip_existing=False)

            assert result is True
            assert "sub-01" in wrapper.results["success"]

    def test_process_participant_failure(self, test_dirs, mock_mriqc_version):
        """Test failed participant processing."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Mock subprocess failure
        with patch("mriqc.mriqc_runner.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 1
            mock_result.stderr = "Error occurred"
            mock_run.return_value = mock_result

            result = wrapper.process_participant(subject_id="01")

            assert result is False
            assert "sub-01" in wrapper.results["failure"]

    def test_process_participant_skip_existing(self, test_dirs, mock_mriqc_version):
        """Test skipping already processed participant."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create existing output
        output_file = wrapper.mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json"
        output_file.parent.mkdir(parents=True)
        output_file.write_text("{}")

        # Mock subprocess (should not be called)
        with patch("mriqc.mriqc_runner.subprocess.run") as mock_run:
            result = wrapper.process_participant(subject_id="01", skip_existing=True)

            assert result is True
            assert "sub-01" in wrapper.results["skipped"]
            mock_run.assert_not_called()

    def test_process_all_participants_with_labels(self, test_dirs, mock_mriqc_version):
        """Test processing multiple specified participants."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create mock output files first
        for sub in ["01", "02"]:
            output_file = (
                wrapper.mriqc_dir / f"sub-{sub}" / "anat" / f"sub-{sub}_T1w.json"
            )
            output_file.parent.mkdir(parents=True)
            output_file.write_text("{}")

        # Mock subprocess
        with patch("mriqc.mriqc_runner.subprocess.run") as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "Success"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            summary = wrapper.process_all_participants(
                participant_labels=["01", "02"],
                skip_existing=False
            )

            assert summary["success"] == 2
            assert summary["total"] == 2

    def test_process_all_participants_discover_subjects(
        self, test_dirs, mock_mriqc_version
    ):
        """Test processing all participants with auto-discovery."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create mock output files first
        for sub in ["01", "02"]:
            output_file = (
                wrapper.mriqc_dir
                / f"sub-{sub}"
                / "anat"
                / f"sub-{sub}_T1w.json"
            )
            output_file.parent.mkdir(parents=True)
            output_file.write_text("{}")

        # Mock BIDSLayout
        with patch("mriqc.mriqc_runner.BIDSLayout") as mock_layout:
            mock_layout_instance = Mock()
            mock_layout_instance.get_subjects.return_value = ["01", "02"]
            mock_layout.return_value = mock_layout_instance

            # Mock subprocess
            with patch("mriqc.mriqc_runner.subprocess.run") as mock_run:
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "Success"
                mock_result.stderr = ""
                mock_run.return_value = mock_result

                summary = wrapper.process_all_participants(skip_existing=False)

                assert summary["success"] == 2
                mock_layout.assert_called_once_with(test_dirs["bids_dir"], validate=False)


class TestMRIQCWrapperOutputs:
    """Test MRIQC output discovery and management."""

    def test_find_mriqc_outputs_single_file(self, test_dirs, mock_mriqc_version):
        """Test finding single MRIQC output file."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create mock output
        output_file = wrapper.mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json"
        output_file.parent.mkdir(parents=True)
        output_file.write_text("{}")

        outputs = wrapper.find_mriqc_outputs(subject_id="01")

        assert len(outputs) == 1
        assert outputs[0] == output_file

    def test_find_mriqc_outputs_multiple_files(self, test_dirs, mock_mriqc_version):
        """Test finding multiple MRIQC output files."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create mock outputs
        anat_file = wrapper.mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json"
        func_file = (
            wrapper.mriqc_dir
            / "sub-01"
            / "func"
            / "sub-01_task-rest_bold.json"
        )

        anat_file.parent.mkdir(parents=True)
        func_file.parent.mkdir(parents=True)
        anat_file.write_text("{}")
        func_file.write_text("{}")

        outputs = wrapper.find_mriqc_outputs(subject_id="01")

        assert len(outputs) == 2

    def test_find_mriqc_outputs_with_session(self, test_dirs, mock_mriqc_version):
        """Test finding MRIQC outputs for specific session."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create mock output with session
        output_file = (
            wrapper.mriqc_dir
            / "sub-01"
            / "ses-01"
            / "anat"
            / "sub-01_ses-01_T1w.json"
        )
        output_file.parent.mkdir(parents=True)
        output_file.write_text("{}")

        outputs = wrapper.find_mriqc_outputs(subject_id="01", session_id="01")

        assert len(outputs) == 1
        assert "ses-01" in str(outputs[0])

    def test_find_mriqc_outputs_with_modality(self, test_dirs, mock_mriqc_version):
        """Test finding MRIQC outputs filtered by modality."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create mock outputs including a potential false positive
        t1_file = wrapper.mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json"
        t2_file = wrapper.mriqc_dir / "sub-01" / "anat" / "sub-01_T2w.json"
        # This should NOT match when filtering for T1w (false positive test)
        false_positive = wrapper.mriqc_dir / "sub-01" / "func" / "sub-01_acq-T1w_bold.json"

        t1_file.parent.mkdir(parents=True, exist_ok=True)
        t2_file.parent.mkdir(parents=True, exist_ok=True)
        false_positive.parent.mkdir(parents=True, exist_ok=True)
        t1_file.write_text("{}")
        t2_file.write_text("{}")
        false_positive.write_text("{}")

        outputs = wrapper.find_mriqc_outputs(subject_id="01", modality="T1w")

        # Should only match the actual T1w file, not the bold file with T1w in acquisition
        assert len(outputs) == 1
        assert outputs[0] == t1_file

    def test_find_mriqc_outputs_no_files(self, test_dirs, mock_mriqc_version):
        """Test finding MRIQC outputs when none exist."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        outputs = wrapper.find_mriqc_outputs(subject_id="01")

        assert len(outputs) == 0


class TestMRIQCWrapperSummary:
    """Test result tracking and summary functionality."""

    def test_get_processing_summary(self, test_dirs, mock_mriqc_version):
        """Test getting processing summary."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        wrapper.results["success"] = ["sub-01", "sub-02"]
        wrapper.results["failure"] = ["sub-03"]
        wrapper.results["skipped"] = ["sub-04"]

        summary = wrapper.get_processing_summary()

        assert summary["total"] == 4
        assert summary["success"] == 2
        assert summary["failure"] == 1
        assert summary["skipped"] == 1

    def test_save_processing_summary(self, test_dirs, mock_mriqc_version):
        """Test saving processing summary to file."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        wrapper.results["success"] = ["sub-01"]

        output_path = wrapper.save_processing_summary()

        assert output_path.exists()
        with open(output_path) as f:
            saved_summary = json.load(f)
            assert "timestamp" in saved_summary
            assert "mriqc_version" in saved_summary
            assert saved_summary["success"] == 1

    def test_create_dataset_description(self, test_dirs, mock_mriqc_version):
        """Test creating dataset_description.json."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        desc_path = wrapper.create_dataset_description()

        assert desc_path.exists()
        with open(desc_path) as f:
            desc = json.load(f)
            assert desc["Name"] == "MRIQC - MRI Quality Control"
            assert desc["DatasetType"] == "derivative"
            assert "GeneratedBy" in desc
            assert len(desc["GeneratedBy"]) == 2

    def test_create_dataset_description_skip_existing(
        self, test_dirs, mock_mriqc_version
    ):
        """Test that existing dataset_description.json is not overwritten."""
        wrapper = MRIQCWrapper(
            bids_dir=test_dirs["bids_dir"],
            output_dir=test_dirs["output_dir"],
        )

        # Create existing file
        desc_path = wrapper.mriqc_dir / "dataset_description.json"
        desc_path.write_text('{"Name": "Existing"}')

        # Should not overwrite
        returned_path = wrapper.create_dataset_description()

        assert returned_path == desc_path
        with open(desc_path) as f:
            desc = json.load(f)
            assert desc["Name"] == "Existing"
