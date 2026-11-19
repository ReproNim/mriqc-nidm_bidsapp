#!/usr/bin/env python3
"""
Unit tests for the run module.

These tests verify the CLI argument parsing and passthrough functionality.
"""


import pytest

from src.utils import owned_mriqc_option, parse_mriqc_args


class TestParseMriqcArgs:
    """Test MRIQC argument parsing functionality."""

    def test_zero_padded_labels_keep_their_padding(self):
        # task-01 and task-1 are different BIDS entities.
        assert parse_mriqc_args(["--task-id", "01"]) == {"task_id": "01"}
        assert parse_mriqc_args(["--task-id=01"]) == {"task_id": "01"}
        assert parse_mriqc_args(["--task-id", "01", "02", "rest"]) == {
            "task_id": ["01", "02", "rest"]}
        assert parse_mriqc_args(["--run-id", "01", "2"]) == {"run_id": ["01", "2"]}

    def test_parse_key_value_pairs(self):
        """Test parsing key-value argument pairs."""
        args = ["--mem", "16G", "--nprocs", "12", "--omp-nthreads", "8"]
        result = parse_mriqc_args(args)

        assert result == {"mem": "16G", "nprocs": "12", "omp_nthreads": "8"}

    def test_parse_boolean_flags(self):
        """Test parsing boolean flag arguments."""
        args = ["--ica", "--no-sub"]
        result = parse_mriqc_args(args)

        assert result == {"ica": True, "no_sub": True}

    def test_parse_mixed_args(self):
        """Test parsing mixed key-value and boolean arguments."""
        args = ["--mem", "16G", "--ica", "--nprocs", "4"]
        result = parse_mriqc_args(args)

        assert result == {"mem": "16G", "ica": True, "nprocs": "4"}

    def test_parse_multiple_values(self):
        args = ["--modalities", "T1w", "bold", "--nprocs", "4"]
        assert parse_mriqc_args(args) == {"modalities": ["T1w", "bold"], "nprocs": "4"}

    def test_parse_short_modalities_flag(self):
        assert parse_mriqc_args(["-m", "T1w", "bold"]) == {"modalities": ["T1w", "bold"]}

    def test_parse_equals_form(self):
        args = ["--bids-filter-file=/x/my_filter.json", "--mem=16G"]
        assert parse_mriqc_args(args) == {
            "bids_filter_file": "/x/my_filter.json", "mem": "16G"}

    def test_parse_empty_args(self):
        """Test parsing empty argument list."""
        args = []
        result = parse_mriqc_args(args)

        assert result == {}

    def test_parse_number_like_value_stays_a_string(self):
        """A value is a string unless MRIQC's option is known to be numeric."""
        args = ["--fd-radius", "45.5"]
        result = parse_mriqc_args(args)

        assert result == {"fd_radius": "45.5"}

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
        assert result["nprocs"] == "12"
        assert result["omp_nthreads"] == "8"


class TestOwnedOptions:
    """owned_mriqc_option finds the pass-through flags the app owns."""

    @pytest.mark.parametrize("typed, flag", [
        (["--participant_label", "2"], "--participant_label"),
        (["--participant-label", "2"], "--participant-label"),
        (["--participant_label=2"], "--participant_label"),
        (["--participant_lab", "2"], "--participant_lab"),
        (["--ica", "--session-id", "2"], "--session-id"),
        (["--session_id=2"], "--session_id"),
    ])
    def test_finds_the_owned_flag(self, typed, flag):
        assert owned_mriqc_option(typed)[0] == flag

    @pytest.mark.parametrize("typed", [
        [], ["--task-id", "01"], ["--fd_thres", "0.3"], ["-m", "T1w"],
        ["--bids-filter-file=participant_label"],
    ])
    def test_ignores_everything_else(self, typed):
        assert owned_mriqc_option(typed) is None
