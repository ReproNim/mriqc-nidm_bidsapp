"""
Unit tests for nidm_converter module

Tests NIDM detection and copying functionality.
"""

import logging
import tempfile
from pathlib import Path

import pytest

from src.nidm_converter.nidm_converter import (
    NIDMInputNotRetrieved,
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

        result = detect_existing_nidm(
            subject_id="01", nidm_input_dir=nidm_input_dir, logger=logger
        )

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

        result = detect_existing_nidm(
            subject_id="02", nidm_input_dir=nidm_input_dir, logger=logger
        )

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

        result = detect_existing_nidm(
            subject_id="03", nidm_input_dir=nidm_input_dir, logger=logger
        )

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

        result = detect_existing_nidm(
            subject_id="04", nidm_input_dir=nidm_input_dir, logger=logger
        )

        assert result is not None
        assert result == json_ld_file
        assert result.suffix == ".json-ld"


def test_detect_existing_nidm_no_directory(logger):
    """Test when NIDM directory doesn't exist"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"

        result = detect_existing_nidm(
            subject_id="99", nidm_input_dir=nidm_input_dir, logger=logger
        )

        assert result is None


def test_detect_existing_nidm_empty_directory(logger):
    """Test when NIDM directory exists but is empty"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nidm_input_dir = Path(tmpdir) / "NIDM"
        nidm_dir = nidm_input_dir / "sub-05"
        nidm_dir.mkdir(parents=True)

        result = detect_existing_nidm(
            subject_id="05", nidm_input_dir=nidm_input_dir, logger=logger
        )

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


# Session-aware lookup. ABIDE II UCLA_Long ships its input NIDM per session,
# at sub-<id>/ses-<n>/nidm.ttl, with nothing directly under sub-<id>/.
def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("@prefix nidm: <http://purl.org/nidash/nidm#> .")
    return path


def test_detect_existing_nidm_session_layout(tmp_path, logger):
    """A session-level run finds sub-<id>/ses-<s>/nidm.ttl"""
    _touch(tmp_path / "sub-51209" / "ses-1" / "nidm.ttl")
    wanted = _touch(tmp_path / "sub-51209" / "ses-2" / "nidm.ttl")

    result = detect_existing_nidm(
        subject_id="51209", nidm_input_dir=tmp_path, session_id="2", logger=logger
    )
    assert result == wanted


def test_detect_existing_nidm_session_named_ttl(tmp_path, logger):
    """sub-<id>/ses-<s>/sub-<id>_ses-<s>.ttl is the second choice"""
    wanted = _touch(tmp_path / "sub-01" / "ses-a" / "sub-01_ses-a.ttl")

    result = detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, session_id="a", logger=logger
    )
    assert result == wanted


def test_detect_existing_nidm_session_beats_subject_level(tmp_path, logger):
    """The session file is more specific than the subject-level one"""
    _touch(tmp_path / "sub-01" / "nidm.ttl")
    wanted = _touch(tmp_path / "sub-01" / "ses-a" / "nidm.ttl")

    result = detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, session_id="a", logger=logger
    )
    assert result == wanted


def test_detect_existing_nidm_session_falls_back_to_subject(tmp_path, logger):
    """With no session file, the subject-level nidm.ttl is used"""
    wanted = _touch(tmp_path / "sub-01" / "nidm.ttl")

    result = detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, session_id="a", logger=logger
    )
    assert result == wanted


def test_detect_existing_nidm_dataset_level_fallback(tmp_path, logger):
    """<dir>/nidm.ttl is the last resort"""
    wanted = _touch(tmp_path / "nidm.ttl")

    result = detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, session_id="a", logger=logger
    )
    assert result == wanted


def test_detect_existing_nidm_subject_glob_before_dataset_level(tmp_path, logger):
    """Any TTL under sub-<id>/ still wins over the dataset-level file"""
    _touch(tmp_path / "nidm.ttl")
    wanted = _touch(tmp_path / "sub-01" / "other.ttl")

    result = detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, logger=logger
    )
    assert result == wanted


def test_detect_existing_nidm_session_via_bids_convention(tmp_path, logger):
    """The BIDS/../NIDM convention honours the session too"""
    bids = tmp_path / "BIDS"
    bids.mkdir()
    wanted = _touch(tmp_path / "NIDM" / "sub-01" / "ses-2" / "nidm.ttl")

    result = detect_existing_nidm(
        subject_id="01", bids_dir=bids, session_id="2", logger=logger
    )
    assert result == wanted


# The app writes nidm.ttl through a temporary `.nidm.XXXX.ttl` in the subject
# directory. One left by a killed run is never an input NIDM, also when the
# NIDM input directory is the output directory.
def test_detect_existing_nidm_ignores_a_temporary_nidm_file(tmp_path, logger):
    _touch(tmp_path / "sub-01" / ".nidm.k1ll3d00.ttl")
    assert detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, logger=logger) is None

    wanted = _touch(tmp_path / "sub-01" / "sub-01.ttl")
    assert detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, logger=logger) == wanted


def test_detect_existing_nidm_ignores_a_temporary_before_the_dataset_file(tmp_path, logger):
    _touch(tmp_path / "sub-01" / ".nidm.k1ll3d00.ttl")
    wanted = _touch(tmp_path / "nidm.ttl")
    assert detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, logger=logger) == wanted


# An unfetched git-annex file is a symbolic link to a missing object. The
# first candidate present decides, and a broken link counts as present.
def _broken(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(path.parent / ".missing-annex-object")
    return path


@pytest.mark.parametrize("relative", [
    "sub-01/ses-a/nidm.ttl",
    "sub-01/ses-a/sub-01_ses-a.ttl",
    "sub-01/nidm.ttl",
    "sub-01/other.ttl",
    "nidm.ttl",
])
def test_detect_existing_nidm_raises_on_the_broken_file_it_would_use(
    tmp_path, logger, relative
):
    link = _broken(tmp_path / relative)
    with pytest.raises(NIDMInputNotRetrieved) as raised:
        detect_existing_nidm(
            subject_id="01", nidm_input_dir=tmp_path, session_id="a",
            logger=logger,
        )
    assert raised.value.path == link
    assert f"datalad get {link}" in str(raised.value)


def test_detect_existing_nidm_broken_session_file_does_not_fall_through(
    tmp_path, logger
):
    link = _broken(tmp_path / "sub-01" / "ses-a" / "nidm.ttl")
    _touch(tmp_path / "sub-01" / "nidm.ttl")
    _touch(tmp_path / "nidm.ttl")
    with pytest.raises(NIDMInputNotRetrieved) as raised:
        detect_existing_nidm(
            subject_id="01", nidm_input_dir=tmp_path, session_id="a",
            logger=logger,
        )
    assert raised.value.path == link


def test_detect_existing_nidm_ignores_a_broken_file_it_would_not_reach(
    tmp_path, logger
):
    _broken(tmp_path / "nidm.ttl")
    _broken(tmp_path / "sub-01" / "z.ttl")
    _broken(tmp_path / "sub-01" / "ses-b" / "nidm.ttl")
    wanted = _touch(tmp_path / "sub-01" / "ses-a" / "nidm.ttl")
    assert detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, session_id="a", logger=logger
    ) == wanted

    other = _touch(tmp_path / "sub-01" / "a.ttl")
    assert detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, logger=logger
    ) == other


def test_detect_existing_nidm_link_loop_counts_as_broken(tmp_path, logger):
    link = tmp_path / "nidm.ttl"
    link.symlink_to(link)
    with pytest.raises(NIDMInputNotRetrieved):
        detect_existing_nidm(subject_id="01", nidm_input_dir=tmp_path, logger=logger)


def test_detect_existing_nidm_skips_a_session_link_to_a_directory(tmp_path, logger):
    (tmp_path / "elsewhere").mkdir()
    link = tmp_path / "sub-01" / "ses-a" / "nidm.ttl"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "elsewhere")
    wanted = _touch(tmp_path / "nidm.ttl")
    assert detect_existing_nidm(
        subject_id="01", nidm_input_dir=tmp_path, session_id="a", logger=logger
    ) == wanted
