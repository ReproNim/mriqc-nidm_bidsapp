"""
Unit tests for json_to_csv module

Tests the MRIQC JSON to CSV conversion functionality.
"""

import json
import logging
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from nidm_converter.json_to_csv import (
    convert_mriqc_json_to_csv,
    create_software_metadata_csv,
    extract_bids_info,
    remove_keys,
)


# Fixtures
@pytest.fixture
def sample_mriqc_json():
    """Sample MRIQC JSON data structure"""
    return {
        "bids_meta": {
            "subject": "01",
            "datatype": "anat",
            "modality": "T1w",
        },
        "provenance": {
            "software": "mriqc",
            "version": "23.1.0",
            "md5sum": "abc123",
        },
        "cjv": 0.35,
        "cnr": 3.2,
        "efc": 0.58,
        "fber": 12000.5,
        "qi_1": 0.0,
        "qi_2": 0.0,
        "size_x": 256,
        "size_y": 256,
        "size_z": 176,
        "spacing_x": 1.0,
        "spacing_y": 1.0,
        "spacing_z": 1.0,
        "snr_total": 8.5,
    }


@pytest.fixture
def logger():
    """Test logger"""
    logger = logging.getLogger("test_json_to_csv")
    logger.setLevel(logging.DEBUG)
    return logger


# Tests for remove_keys
def test_remove_keys_single():
    """Test removing a single key"""
    data = {"a": 1, "b": 2, "c": 3}
    result = remove_keys(data, ["b"])
    assert result == {"a": 1, "c": 3}


def test_remove_keys_multiple():
    """Test removing multiple keys"""
    data = {"a": 1, "b": 2, "c": 3, "d": 4}
    result = remove_keys(data, ["b", "d"])
    assert result == {"a": 1, "c": 3}


def test_remove_keys_nonexistent():
    """Test removing non-existent keys (should not error)"""
    data = {"a": 1, "b": 2}
    result = remove_keys(data, ["c", "d"])
    assert result == {"a": 1, "b": 2}


def test_remove_keys_empty_list():
    """Test with empty removal list"""
    data = {"a": 1, "b": 2}
    result = remove_keys(data, [])
    assert result == {"a": 1, "b": 2}


# Tests for create_software_metadata_csv
def test_create_software_metadata_csv_with_provenance(sample_mriqc_json, logger):
    """Test software metadata creation with provenance data"""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test.csv"
        metadata_path = create_software_metadata_csv(
            sample_mriqc_json, csv_path, logger
        )

        # Check file was created
        assert metadata_path.exists()
        assert metadata_path.name == "test_software_metadata.csv"

        # Read and verify contents
        df = pd.read_csv(metadata_path)
        assert len(df) == 1
        assert df["title"][0] == "mriqc"
        assert df["version"][0] == "23.1.0"
        assert "mriqc" in df["description"][0].lower()
        assert df["url"][0] == "https://mriqc.readthedocs.io/en/stable/"
        assert "SCR_022942" in df["ID"][0]


def test_create_software_metadata_csv_without_provenance(logger):
    """Test software metadata creation without provenance (uses defaults)"""
    data = {"some_metric": 1.5}  # No provenance field

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test.csv"
        metadata_path = create_software_metadata_csv(data, csv_path, logger)

        # Check file was created with defaults
        df = pd.read_csv(metadata_path)
        assert df["title"][0] == "mriqc"
        assert df["version"][0] == "unknown"


# Tests for extract_bids_info
def test_extract_bids_info_from_bids_meta(sample_mriqc_json, logger):
    """Test BIDS info extraction from bids_meta field"""
    json_path = Path("sub-01_ses-02_T1w.json")
    subj, ses, task, run = extract_bids_info(json_path, sample_mriqc_json, logger)

    assert subj == "01"  # From bids_meta
    assert ses == "02"  # From filename
    assert task == "None"  # Anatomical data
    assert run == ""


def test_extract_bids_info_from_filename_only(logger):
    """Test BIDS info extraction from filename (no bids_meta)"""
    json_path = Path("sub-99_ses-03_task-rest_run-1_bold.json")
    data = {}  # No bids_meta

    subj, ses, task, run = extract_bids_info(json_path, data, logger)

    assert subj == "99"
    assert ses == "03"
    assert task == "rest"
    assert run == "1"


def test_extract_bids_info_minimal_filename(logger):
    """Test with minimal filename (just subject)"""
    json_path = Path("sub-42_T1w.json")
    data = {}

    subj, ses, task, run = extract_bids_info(json_path, data, logger)

    assert subj == "42"
    assert ses == "01"  # Default
    assert task == "None"  # Anatomical data (T1w) has task="None"
    assert run == ""


def test_extract_bids_info_from_path_with_session(logger):
    """Test extraction when session is in path"""
    json_path = Path("/data/BIDS/sub-01/ses-baseline/anat/sub-01_T1w.json")
    data = {}

    subj, ses, task, run = extract_bids_info(json_path, data, logger)

    assert subj == "01"
    assert ses == "baseline"


# Tests for convert_mriqc_json_to_csv (main function)
def test_convert_mriqc_json_to_csv_success(sample_mriqc_json, logger):
    """Test full conversion pipeline"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test JSON file
        json_file = Path(tmpdir) / "sub-01_ses-01_T1w.json"
        with open(json_file, "w") as f:
            json.dump(sample_mriqc_json, f)

        # Convert
        output_csv = Path(tmpdir) / "output.csv"
        csv_path, metadata_path = convert_mriqc_json_to_csv(
            json_file, output_csv, logger
        )

        # Verify outputs exist
        assert csv_path.exists()
        assert metadata_path.exists()

        # Verify CSV contents (read with string dtypes for BIDS identifiers)
        # keep_default_na=False prevents pandas from interpreting "None" string as NaN
        df = pd.read_csv(
            csv_path,
            dtype={"subject_id": str, "ses": str, "task": str, "run": str},
            keep_default_na=False,
        )
        assert len(df) == 1

        # Check required NIDM fields were added
        assert "subject_id" in df.columns
        assert "ses" in df.columns
        assert "task" in df.columns
        assert "run" in df.columns
        assert "source_url" in df.columns

        assert df["subject_id"][0] == "01"
        assert df["ses"][0] == "01"
        assert df["task"][0] == "None"  # Anatomical data (T1w) has task="None"

        # Check unwanted fields were removed
        assert "bids_meta" not in df.columns
        assert "provenance" not in df.columns
        assert "qi_1" not in df.columns
        assert "qi_2" not in df.columns
        assert "size_x" not in df.columns

        # Check metrics are preserved
        assert "cjv" in df.columns
        assert "cnr" in df.columns
        assert df["cjv"][0] == 0.35
        assert df["cnr"][0] == 3.2


def test_convert_mriqc_json_to_csv_file_not_found(logger):
    """Test error handling for missing JSON file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / "nonexistent.json"
        output_csv = Path(tmpdir) / "output.csv"

        with pytest.raises(FileNotFoundError):
            convert_mriqc_json_to_csv(json_file, output_csv, logger)


def test_convert_mriqc_json_to_csv_invalid_json(logger):
    """Test error handling for malformed JSON"""
    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / "invalid.json"

        # Create invalid JSON file
        with open(json_file, "w") as f:
            f.write("{ invalid json }")

        output_csv = Path(tmpdir) / "output.csv"

        with pytest.raises(json.JSONDecodeError):
            convert_mriqc_json_to_csv(json_file, output_csv, logger)


def test_convert_mriqc_json_to_csv_functional_data(logger):
    """Test conversion with functional (BOLD) data"""
    func_data = {
        "bids_meta": {
            "subject": "02",
            "datatype": "func",
            "modality": "bold",
        },
        "provenance": {
            "software": "mriqc",
            "version": "23.1.0",
        },
        "fd_mean": 0.25,
        "dvars_std": 1.5,
        "tsnr": 45.2,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / "sub-02_task-rest_run-2_bold.json"
        with open(json_file, "w") as f:
            json.dump(func_data, f)

        output_csv = Path(tmpdir) / "output.csv"
        csv_path, _ = convert_mriqc_json_to_csv(json_file, output_csv, logger)

        df = pd.read_csv(
            csv_path,
            dtype={"subject_id": str, "ses": str, "task": str, "run": str},
            keep_default_na=False,
        )
        assert df["subject_id"][0] == "02"
        assert df["task"][0] == "rest"
        assert df["run"][0] == "2"
        assert "fd_mean" in df.columns
        assert "dvars_std" in df.columns


def test_convert_mriqc_json_to_csv_creates_default_logger():
    """Test that conversion works without providing a logger"""
    sample_data = {
        "provenance": {"software": "mriqc", "version": "23.1.0"},
        "cjv": 0.35,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / "sub-01_T1w.json"
        with open(json_file, "w") as f:
            json.dump(sample_data, f)

        output_csv = Path(tmpdir) / "output.csv"

        # Call without logger - should create default
        csv_path, _ = convert_mriqc_json_to_csv(json_file, output_csv)

        assert csv_path.exists()


def test_convert_preserves_all_metrics(sample_mriqc_json, logger):
    """Test that all valid metrics are preserved in output"""
    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / "sub-01_T1w.json"
        with open(json_file, "w") as f:
            json.dump(sample_mriqc_json, f)

        output_csv = Path(tmpdir) / "output.csv"
        csv_path, _ = convert_mriqc_json_to_csv(json_file, output_csv, logger)

        df = pd.read_csv(csv_path)

        # Check all metrics are present
        expected_metrics = ["cjv", "cnr", "efc", "fber", "snr_total"]
        for metric in expected_metrics:
            assert metric in df.columns
            assert df[metric][0] == sample_mriqc_json[metric]
