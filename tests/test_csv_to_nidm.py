"""
Tests for csv_to_nidm module.

This module tests the csv2nidm wrapper functionality including:
- Tool availability checking
- Standalone NIDM creation
- Existing NIDM augmentation
- Input validation
- Error handling
- CLI interface
"""

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from nidm_converter.csv_to_nidm import (
    CSV2NIDM_TOOL,
    check_csv2nidm_available,
    convert_csv_to_nidm,
    main,
)


# Fixtures


@pytest.fixture
def tmp_files(tmp_path):
    """Create temporary test files."""
    csv_file = tmp_path / "mriqc_results.csv"
    dictionary_csv = tmp_path / "mriqc_dictionary_v1.csv"
    software_metadata_csv = tmp_path / "software_metadata.csv"
    output_ttl = tmp_path / "output" / "sub-01.ttl"
    existing_nidm = tmp_path / "existing" / "nidm.ttl"

    # Create test files
    csv_file.write_text("subject_id,iqm1,iqm2\nsub-01,1.0,2.0\n")
    dictionary_csv.write_text("column,label\niqm1,IQM1\niqm2,IQM2\n")
    software_metadata_csv.write_text("Software,Version\nMRIQC,23.1.0\n")

    # Create existing NIDM directory
    existing_nidm.parent.mkdir(parents=True, exist_ok=True)
    existing_nidm.write_text("@prefix : <http://example.org/> .\n")

    return {
        "csv_file": csv_file,
        "dictionary_csv": dictionary_csv,
        "software_metadata_csv": software_metadata_csv,
        "output_ttl": output_ttl,
        "existing_nidm": existing_nidm,
    }


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    return MagicMock(spec=logging.Logger)


# Tests for check_csv2nidm_available


def test_check_csv2nidm_available_true():
    """Test csv2nidm tool availability check when tool exists."""
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"):
        assert check_csv2nidm_available() is True


def test_check_csv2nidm_available_false():
    """Test csv2nidm tool availability check when tool doesn't exist."""
    with patch("shutil.which", return_value=None):
        assert check_csv2nidm_available() is False


# Tests for convert_csv_to_nidm - Success Cases


def test_convert_csv_to_nidm_standalone_success(tmp_files, mock_logger):
    """Test successful standalone NIDM creation."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Conversion successful"
    mock_result.stderr = ""

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", return_value=mock_result
    ) as mock_run:

        result = convert_csv_to_nidm(
            csv_file=tmp_files["csv_file"],
            dictionary_csv=tmp_files["dictionary_csv"],
            software_metadata_csv=tmp_files["software_metadata_csv"],
            output_ttl=tmp_files["output_ttl"],
            logger=mock_logger,
        )

        assert result is True
        assert mock_run.called
        assert tmp_files["output_ttl"].parent.exists()

        # Verify command construction
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == CSV2NIDM_TOOL
        assert "-out" in cmd
        assert str(tmp_files["output_ttl"]) in cmd
        assert "-csv" in cmd
        assert "-csv_map" in cmd
        assert "-derivative" in cmd
        assert "-no_concepts" in cmd


def test_convert_csv_to_nidm_augmentation_success(tmp_files, mock_logger):
    """Test successful NIDM augmentation."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Augmentation successful"
    mock_result.stderr = ""

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", return_value=mock_result
    ) as mock_run:

        result = convert_csv_to_nidm(
            csv_file=tmp_files["csv_file"],
            dictionary_csv=tmp_files["dictionary_csv"],
            software_metadata_csv=tmp_files["software_metadata_csv"],
            output_ttl=tmp_files["output_ttl"],
            existing_nidm=tmp_files["existing_nidm"],
            logger=mock_logger,
        )

        assert result is True
        assert mock_run.called

        # Verify command uses -nidm flag instead of -out
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == CSV2NIDM_TOOL
        assert "-nidm" in cmd
        assert str(tmp_files["existing_nidm"]) in cmd
        assert "-out" not in cmd


def test_convert_csv_to_nidm_creates_output_directory(tmp_files, mock_logger):
    """Test that output directory is created if it doesn't exist."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    # Ensure output directory doesn't exist
    assert not tmp_files["output_ttl"].parent.exists()

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", return_value=mock_result
    ):

        convert_csv_to_nidm(
            csv_file=tmp_files["csv_file"],
            dictionary_csv=tmp_files["dictionary_csv"],
            software_metadata_csv=tmp_files["software_metadata_csv"],
            output_ttl=tmp_files["output_ttl"],
            logger=mock_logger,
        )

        # Verify directory was created
        assert tmp_files["output_ttl"].parent.exists()


def test_convert_csv_to_nidm_no_logger(tmp_files):
    """Test conversion works without explicit logger."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", return_value=mock_result
    ):

        result = convert_csv_to_nidm(
            csv_file=tmp_files["csv_file"],
            dictionary_csv=tmp_files["dictionary_csv"],
            software_metadata_csv=tmp_files["software_metadata_csv"],
            output_ttl=tmp_files["output_ttl"],
        )

        assert result is True


# Tests for convert_csv_to_nidm - Error Cases


def test_convert_csv_to_nidm_tool_not_available(tmp_files, mock_logger):
    """Test error when csv2nidm tool is not available."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="csv2nidm not available"):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"],
                dictionary_csv=tmp_files["dictionary_csv"],
                software_metadata_csv=tmp_files["software_metadata_csv"],
                output_ttl=tmp_files["output_ttl"],
                logger=mock_logger,
            )


def test_convert_csv_to_nidm_csv_file_not_found(tmp_files, mock_logger):
    """Test error when CSV file doesn't exist."""
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"):
        with pytest.raises(FileNotFoundError, match="CSV file not found"):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"].parent / "nonexistent.csv",
                dictionary_csv=tmp_files["dictionary_csv"],
                software_metadata_csv=tmp_files["software_metadata_csv"],
                output_ttl=tmp_files["output_ttl"],
                logger=mock_logger,
            )


def test_convert_csv_to_nidm_dictionary_not_found(tmp_files, mock_logger):
    """Test error when dictionary CSV doesn't exist."""
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"):
        with pytest.raises(FileNotFoundError, match="Dictionary CSV not found"):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"],
                dictionary_csv=tmp_files["dictionary_csv"].parent / "nonexistent.csv",
                software_metadata_csv=tmp_files["software_metadata_csv"],
                output_ttl=tmp_files["output_ttl"],
                logger=mock_logger,
            )


def test_convert_csv_to_nidm_software_metadata_not_found(tmp_files, mock_logger):
    """Test error when software metadata CSV doesn't exist."""
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"):
        with pytest.raises(
            FileNotFoundError, match="Software metadata CSV not found"
        ):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"],
                dictionary_csv=tmp_files["dictionary_csv"],
                software_metadata_csv=tmp_files["software_metadata_csv"].parent
                / "nonexistent.csv",
                output_ttl=tmp_files["output_ttl"],
                logger=mock_logger,
            )


def test_convert_csv_to_nidm_existing_nidm_not_found(tmp_files, mock_logger):
    """Test error when existing NIDM file doesn't exist."""
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"):
        with pytest.raises(FileNotFoundError, match="Existing NIDM file not found"):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"],
                dictionary_csv=tmp_files["dictionary_csv"],
                software_metadata_csv=tmp_files["software_metadata_csv"],
                output_ttl=tmp_files["output_ttl"],
                existing_nidm=tmp_files["existing_nidm"].parent / "nonexistent.ttl",
                logger=mock_logger,
            )


def test_convert_csv_to_nidm_execution_failure(tmp_files, mock_logger):
    """Test error when csv2nidm execution fails."""
    # Create CalledProcessError to simulate non-zero exit code
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["csv2nidm"],
        output="",
        stderr="Error: Invalid CSV format"
    )

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", side_effect=error
    ):

        with pytest.raises(RuntimeError, match="csv2nidm failed"):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"],
                dictionary_csv=tmp_files["dictionary_csv"],
                software_metadata_csv=tmp_files["software_metadata_csv"],
                output_ttl=tmp_files["output_ttl"],
                logger=mock_logger,
            )


def test_convert_csv_to_nidm_timeout(tmp_files, mock_logger):
    """Test error when csv2nidm execution times out."""
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired("csv2nidm", 300)
    ):

        with pytest.raises(RuntimeError, match="timed out"):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"],
                dictionary_csv=tmp_files["dictionary_csv"],
                software_metadata_csv=tmp_files["software_metadata_csv"],
                output_ttl=tmp_files["output_ttl"],
                logger=mock_logger,
            )


def test_convert_csv_to_nidm_subprocess_error(tmp_files, mock_logger):
    """Test error when subprocess execution fails."""
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", side_effect=OSError("Permission denied")
    ):

        with pytest.raises(RuntimeError, match="csv2nidm execution failed"):
            convert_csv_to_nidm(
                csv_file=tmp_files["csv_file"],
                dictionary_csv=tmp_files["dictionary_csv"],
                software_metadata_csv=tmp_files["software_metadata_csv"],
                output_ttl=tmp_files["output_ttl"],
                logger=mock_logger,
            )


# Tests for CLI


def test_main_success(tmp_files):
    """Test CLI with successful conversion."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    test_args = [
        "csv_to_nidm.py",
        str(tmp_files["csv_file"]),
        str(tmp_files["dictionary_csv"]),
        str(tmp_files["software_metadata_csv"]),
        str(tmp_files["output_ttl"]),
    ]

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", return_value=mock_result
    ), patch("sys.argv", test_args):

        exit_code = main()
        assert exit_code == 0


def test_main_with_existing_nidm(tmp_files):
    """Test CLI with existing NIDM augmentation."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    test_args = [
        "csv_to_nidm.py",
        str(tmp_files["csv_file"]),
        str(tmp_files["dictionary_csv"]),
        str(tmp_files["software_metadata_csv"]),
        str(tmp_files["output_ttl"]),
        "--existing-nidm",
        str(tmp_files["existing_nidm"]),
    ]

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", return_value=mock_result
    ), patch("sys.argv", test_args):

        exit_code = main()
        assert exit_code == 0


def test_main_verbose(tmp_files):
    """Test CLI with verbose logging."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    test_args = [
        "csv_to_nidm.py",
        str(tmp_files["csv_file"]),
        str(tmp_files["dictionary_csv"]),
        str(tmp_files["software_metadata_csv"]),
        str(tmp_files["output_ttl"]),
        "--verbose",
    ]

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "subprocess.run", return_value=mock_result
    ), patch("sys.argv", test_args):

        exit_code = main()
        assert exit_code == 0


def test_main_file_not_found(tmp_files):
    """Test CLI with missing file."""
    test_args = [
        "csv_to_nidm.py",
        str(tmp_files["csv_file"].parent / "nonexistent.csv"),
        str(tmp_files["dictionary_csv"]),
        str(tmp_files["software_metadata_csv"]),
        str(tmp_files["output_ttl"]),
    ]

    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), patch(
        "sys.argv", test_args
    ):

        exit_code = main()
        assert exit_code == 1
