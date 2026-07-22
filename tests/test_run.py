#!/usr/bin/env python3
"""
Unit tests for the run module.

These tests verify the CLI argument parsing and passthrough functionality.
"""

import sys
from unittest.mock import patch

import pytest

from src.run import main
from src.utils import parse_mriqc_args


class TestParseMriqcArgs:
    """Test MRIQC argument parsing functionality."""

    def test_parse_key_value_pairs(self):
        """Test parsing key-value argument pairs."""
        args = ["--mem", "16G", "--nprocs", "12", "--omp-nthreads", "8"]
        result = parse_mriqc_args(args)

        assert result == {"mem": "16G", "nprocs": 12, "omp_nthreads": 8}

    def test_parse_boolean_flags(self):
        """Test parsing boolean flag arguments."""
        args = ["--ica", "--no-sub"]
        result = parse_mriqc_args(args)

        assert result == {"ica": True, "no_sub": True}

    def test_parse_mixed_args(self):
        """Test parsing mixed key-value and boolean arguments."""
        args = ["--mem", "16G", "--ica", "--nprocs", "4"]
        result = parse_mriqc_args(args)

        assert result == {"mem": "16G", "ica": True, "nprocs": 4}

    def test_parse_empty_args(self):
        """Test parsing empty argument list."""
        args = []
        result = parse_mriqc_args(args)

        assert result == {}

    def test_parse_float_value(self):
        """Test parsing float values."""
        args = ["--fd-radius", "45.5"]
        result = parse_mriqc_args(args)

        assert result == {"fd_radius": 45.5}

    def test_parse_string_value_not_number(self):
        """Test that non-numeric strings are kept as strings."""
        args = ["--mem", "16G", "--work-dir", "/tmp/work"]
        result = parse_mriqc_args(args)

        assert result["mem"] == "16G"
        assert result["work_dir"] == "/tmp/work"

    def test_hyphen_to_underscore_conversion(self):
        """Test that hyphens in arg names are converted to underscores."""
        args = ["--omp-nthreads", "8", "--fd-radius", "50"]
        result = parse_mriqc_args(args)

        assert "omp_nthreads" in result
        assert "fd_radius" in result
        # Verify hyphens are NOT in keys
        assert "omp-nthreads" not in result
        assert "fd-radius" not in result

    def test_parse_consecutive_flags(self):
        """Test parsing multiple consecutive boolean flags."""
        args = ["--ica", "--no-sub", "--dry-run"]
        result = parse_mriqc_args(args)

        assert result == {"ica": True, "no_sub": True, "dry_run": True}

    def test_parse_negative_number(self):
        """Test that negative numbers are handled correctly."""
        # Note: This is an edge case - negative numbers start with '-'
        # but should be treated as values, not flags
        args = ["--threshold", "-0.5"]
        result = parse_mriqc_args(args)

        # Current implementation treats -0.5 as a flag, which is a known limitation
        # This test documents the current behavior
        assert "threshold" in result
        # The -0.5 would be treated as boolean True since it starts with '-'
        assert result["threshold"] is True

    def test_parse_typical_babs_config(self):
        """Test parsing typical BABS config arguments."""
        # These are the exact args from the error log that prompted this feature
        args = ["--mem", "16G", "--nprocs", "12", "--omp-nthreads", "8"]
        result = parse_mriqc_args(args)

        assert result["mem"] == "16G"
        assert result["nprocs"] == 12
        assert result["omp_nthreads"] == 8


def test_main_forwards_babs_session_to_mriqc_and_conversion(tmp_path):
    """BABS's outer --session-label reaches both processing stages."""
    bids_dir = tmp_path / "BIDS"
    output_dir = tmp_path / "output"
    (bids_dir / "sub-01" / "ses-baseline").mkdir(parents=True)

    argv = [
        "mriqc-nidm",
        str(bids_dir),
        str(output_dir),
        "participant",
        "--participant-label",
        "sub-01",
        "--session-label",
        "ses-baseline",
        "--skip-nidm-conversion",
    ]

    with patch.object(sys, "argv", argv):
        with patch("src.run.MRIQCWrapper") as wrapper_cls:
            with patch(
                "src.run.process_subject", return_value=True
            ) as process_subject_mock:
                result = main()

    assert result == 0
    wrapper_cls.return_value.process_participant.assert_called_once()
    assert (
        wrapper_cls.return_value.process_participant.call_args.kwargs["session_id"]
        == "baseline"
    )
    process_subject_mock.assert_called_once()
    assert process_subject_mock.call_args.kwargs["session_id"] == "baseline"
