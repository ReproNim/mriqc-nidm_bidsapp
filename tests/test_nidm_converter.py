"""
Unit tests for nidm_converter module

Tests NIDM detection and copying functionality.
"""

import logging
import tempfile
from pathlib import Path

import pytest

from nidm_converter.nidm_converter import (
    copy_and_prepare_nidm,
    detect_existing_nidm,
    get_supported_nidm_formats,
    is_nidm_file,
)


# Fixtures
@pytest.fixture
def logger():
    """Test logger"""
    logger = logging.getLogger("test_nidm_converter")
    logger.setLevel(logging.DEBUG)
    return logger


# Tests for detect_existing_nidm
def test_detect_existing_nidm_preferred_file(logger):
    """Test detection of preferred nidm.ttl file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create NIDM structure
        nidm_input_dir = Path(tmpdir) / "NIDM"
        nidm_dir = nidm_input_dir / "sub-01"
        nidm_dir.mkdir(parents=True)

        # Create preferred file
        nidm_file = nidm_dir / "nidm.ttl"
        nidm_file.touch()

        # Also create other files to ensure nidm.ttl is preferred
        (nidm_dir / "other.ttl").touch()
        (nidm_dir / "data.jsonld").touch()

        result = detect_existing_nidm(subject_id="01", nidm_input_dir=nidm_input_dir, logger=logger)

        assert result is not None
        assert result == nidm_file
        assert result.name == "nidm.ttl"


def test_detect_existing_nidm_any_ttl_file(logger):
    """Test detection of any .ttl file when nidm.ttl doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"
        nidm_dir = nidm_input_dir / "sub-02"
        nidm_dir.mkdir(parents=True)

        # Create a .ttl file (not nidm.ttl)
        ttl_file = nidm_dir / "data.ttl"
        ttl_file.touch()

        result = detect_existing_nidm(subject_id="02", nidm_input_dir=nidm_input_dir, logger=logger)

        assert result is not None
        assert result == ttl_file
        assert result.suffix == ".ttl"


def test_detect_existing_nidm_jsonld_file(logger):
    """Test detection of .jsonld file when no .ttl files exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"
        nidm_dir = nidm_input_dir / "sub-03"
        nidm_dir.mkdir(parents=True)

        # Create a .jsonld file
        jsonld_file = nidm_dir / "data.jsonld"
        jsonld_file.touch()

        result = detect_existing_nidm(subject_id="03", nidm_input_dir=nidm_input_dir, logger=logger)

        assert result is not None
        assert result == jsonld_file
        assert result.suffix == ".jsonld"


def test_detect_existing_nidm_json_ld_file(logger):
    """Test detection of .json-ld file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"
        nidm_dir = nidm_input_dir / "sub-04"
        nidm_dir.mkdir(parents=True)

        # Create a .json-ld file
        json_ld_file = nidm_dir / "data.json-ld"
        json_ld_file.touch()

        result = detect_existing_nidm(subject_id="04", nidm_input_dir=nidm_input_dir, logger=logger)

        assert result is not None
        assert result == json_ld_file
        assert result.suffix == ".json-ld"


def test_detect_existing_nidm_no_directory(logger):
    """Test when NIDM directory doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"

        result = detect_existing_nidm(subject_id="99", nidm_input_dir=nidm_input_dir, logger=logger)

        assert result is None


def test_detect_existing_nidm_empty_directory(logger):
    """Test when NIDM directory exists but is empty"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"
        nidm_dir = nidm_input_dir / "sub-05"
        nidm_dir.mkdir(parents=True)

        result = detect_existing_nidm(subject_id="05", nidm_input_dir=nidm_input_dir, logger=logger)

        assert result is None


def test_detect_existing_nidm_no_logger():
    """Test that detection works without providing a logger"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"
        nidm_dir = nidm_input_dir / "sub-01"
        nidm_dir.mkdir(parents=True)

        nidm_file = nidm_dir / "nidm.ttl"
        nidm_file.touch()

        # Call without logger - should create default
        result = detect_existing_nidm(subject_id="01", nidm_input_dir=nidm_input_dir)

        assert result is not None
        assert result == nidm_file


# Tests for copy_and_prepare_nidm
def test_copy_and_prepare_nidm_success(logger):
    """Test successful copy of NIDM file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create source file
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()
        source_file = source_dir / "nidm.ttl"
        source_file.write_text("Sample NIDM content")

        # Copy to output
        output_dir = Path(tmpdir) / "output"
        result = copy_and_prepare_nidm(source_file, output_dir, logger)

        # Verify
        assert result.exists()
        assert result.parent == output_dir
        assert result.name == "nidm.ttl"
        assert result.read_text() == "Sample NIDM content"


def test_copy_and_prepare_nidm_file_not_found(logger):
    """Test error when source file doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "nonexistent.ttl"
        output_dir = Path(tmpdir) / "output"

        with pytest.raises(FileNotFoundError):
            copy_and_prepare_nidm(source_file, output_dir, logger)


def test_copy_and_prepare_nidm_creates_directory(logger):
    """Test that output directory is created if it doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "nidm.ttl"
        source_file.write_text("Content")

        output_dir = Path(tmpdir) / "new" / "nested" / "output"

        result = copy_and_prepare_nidm(source_file, output_dir, logger)

        assert output_dir.exists()
        assert result.exists()


def test_copy_and_prepare_nidm_same_path(logger):
    """Test when input and output paths are the same"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_file = Path(tmpdir) / "nidm.ttl"
        nidm_file.write_text("Content")

        # Try to copy to same directory with same name
        result = copy_and_prepare_nidm(nidm_file, Path(tmpdir), logger)

        # Should return same path without copying
        assert result == nidm_file


def test_copy_and_prepare_nidm_preserves_metadata(logger):
    """Test that file metadata is preserved during copy"""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = Path(tmpdir) / "nidm.ttl"
        source_file.write_text("Content")

        # Record original modification time
        original_mtime = source_file.stat().st_mtime

        output_dir = Path(tmpdir) / "output"
        result = copy_and_prepare_nidm(source_file, output_dir, logger)

        # Metadata should be preserved (shutil.copy2)
        assert result.stat().st_mtime == pytest.approx(original_mtime, abs=0.01)


# Tests for helper functions
def test_get_supported_nidm_formats():
    """Test getting supported format list"""
    formats = get_supported_nidm_formats()

    assert isinstance(formats, list)
    assert ".ttl" in formats
    assert ".jsonld" in formats
    assert ".json-ld" in formats
    assert len(formats) == 3


def test_is_nidm_file_true_cases():
    """Test is_nidm_file with valid NIDM files"""
    assert is_nidm_file(Path("data.ttl")) is True
    assert is_nidm_file(Path("data.jsonld")) is True
    assert is_nidm_file(Path("data.json-ld")) is True
    assert is_nidm_file(Path("/path/to/file.ttl")) is True


def test_is_nidm_file_false_cases():
    """Test is_nidm_file with non-NIDM files"""
    assert is_nidm_file(Path("data.csv")) is False
    assert is_nidm_file(Path("data.json")) is False
    assert is_nidm_file(Path("data.txt")) is False
    assert is_nidm_file(Path("data")) is False
    assert is_nidm_file(Path("data.py")) is False
