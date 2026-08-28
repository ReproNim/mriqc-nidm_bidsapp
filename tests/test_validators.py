"""
Tests for src/validators.py.

This module was previously unreferenced and had no coverage. These tests pin
its current behaviour so the wiring in run.py has a contract to rely on.
"""

import pytest

from src.validators import (
    access_check_writable,
    validate_bids_directory,
    validate_nidm_input_directory,
    validate_output_directory,
    validate_participant_labels,
    validate_session_labels,
)


def _bids(root, description=True, subjects=("01",)):
    root.mkdir(parents=True, exist_ok=True)
    if description:
        (root / "dataset_description.json").write_text(
            '{"Name": "test", "BIDSVersion": "1.8.0"}'
        )
    for sub in subjects:
        (root / f"sub-{sub}" / "anat").mkdir(parents=True, exist_ok=True)
    return root


class TestValidateBidsDirectory:
    def test_accepts_minimal_valid_dataset(self, tmp_path):
        assert validate_bids_directory(_bids(tmp_path / "bids")) is True

    def test_rejects_missing_directory(self, tmp_path):
        assert validate_bids_directory(tmp_path / "nope") is False

    def test_rejects_file_masquerading_as_directory(self, tmp_path):
        as_file = tmp_path / "bids"
        as_file.write_text("not a directory")
        assert validate_bids_directory(as_file) is False

    def test_rejects_dataset_without_description(self, tmp_path):
        bids_dir = _bids(tmp_path / "b", description=False)
        assert validate_bids_directory(bids_dir) is False

    def test_rejects_dataset_with_no_subjects(self, tmp_path):
        assert validate_bids_directory(_bids(tmp_path / "b", subjects=())) is False


class TestValidateNidmInputDirectory:
    @pytest.mark.parametrize("ext", [".ttl", ".jsonld", ".json-ld"])
    def test_accepts_each_recognised_extension(self, tmp_path, ext):
        nidm = tmp_path / "NIDM"
        nidm.mkdir()
        (nidm / f"graph{ext}").write_text("")
        assert validate_nidm_input_directory(nidm) is True

    def test_finds_nidm_files_nested_under_subject_dirs(self, tmp_path):
        # Real NIDM inputs live at NIDM/sub-01/nidm.ttl, so the search must recurse.
        nidm = tmp_path / "NIDM"
        (nidm / "sub-01" / "ses-baseline").mkdir(parents=True)
        (nidm / "sub-01" / "ses-baseline" / "nidm.ttl").write_text("")
        assert validate_nidm_input_directory(nidm) is True

    def test_rejects_missing_directory(self, tmp_path):
        assert validate_nidm_input_directory(tmp_path / "nope") is False

    def test_rejects_non_directory(self, tmp_path):
        as_file = tmp_path / "NIDM"
        as_file.write_text("x")
        assert validate_nidm_input_directory(as_file) is False

    def test_rejects_directory_with_no_nidm_files(self, tmp_path):
        nidm = tmp_path / "NIDM"
        nidm.mkdir()
        (nidm / "notes.txt").write_text("")
        assert validate_nidm_input_directory(nidm) is False


class TestValidateOutputDirectory:
    def test_creates_missing_directory_by_default(self, tmp_path):
        target = tmp_path / "out" / "nested"
        assert validate_output_directory(target) is True
        assert target.is_dir()

    def test_does_not_create_when_create_is_false(self, tmp_path):
        target = tmp_path / "out"
        assert validate_output_directory(target, create=False) is False
        assert not target.exists()

    def test_accepts_existing_writable_directory(self, tmp_path):
        assert validate_output_directory(tmp_path) is True

    def test_rejects_path_that_is_a_file(self, tmp_path):
        as_file = tmp_path / "out"
        as_file.write_text("x")
        assert validate_output_directory(as_file) is False

    def test_rejects_read_only_directory(self, tmp_path):
        target = tmp_path / "ro"
        target.mkdir()
        target.chmod(0o555)
        try:
            assert validate_output_directory(target) is False
        finally:
            target.chmod(0o755)

    def test_returns_false_when_creation_is_denied(self, tmp_path):
        # Parent is read-only, so mkdir raises PermissionError. The validator
        # must report it rather than let it escape to the caller.
        parent = tmp_path / "locked"
        parent.mkdir()
        parent.chmod(0o555)
        try:
            assert validate_output_directory(parent / "child") is False
        finally:
            parent.chmod(0o755)


class TestAccessCheckWritable:
    def test_true_for_writable_directory(self, tmp_path):
        assert access_check_writable(tmp_path) is True

    def test_false_for_read_only_directory(self, tmp_path):
        target = tmp_path / "ro"
        target.mkdir()
        target.chmod(0o555)
        try:
            assert access_check_writable(target) is False
        finally:
            target.chmod(0o755)

    def test_leaves_no_probe_file_behind(self, tmp_path):
        access_check_writable(tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestValidateParticipantLabels:
    def test_strips_sub_prefix_and_passes_bare_labels_through(self):
        assert validate_participant_labels(["sub-01", "02"]) == ["01", "02"]

    def test_allows_underscores_and_alphanumerics(self):
        assert validate_participant_labels(["sub-A_1"]) == ["A_1"]

    def test_returns_empty_list_for_empty_input(self):
        assert validate_participant_labels([]) == []

    @pytest.mark.parametrize("bad", ["sub-01/../etc", "01 02", "sub-", "", "a-b"])
    def test_rejects_invalid_labels(self, bad):
        with pytest.raises(ValueError):
            validate_participant_labels([bad])


class TestValidateSessionLabels:
    def test_strips_ses_prefix_and_passes_bare_labels_through(self):
        assert validate_session_labels(["ses-baseline", "followup"]) == [
            "baseline",
            "followup",
        ]

    def test_returns_empty_list_for_empty_input(self):
        assert validate_session_labels([]) == []

    @pytest.mark.parametrize("bad", ["ses-a/b", "a b", "ses-", "", "a-b"])
    def test_rejects_invalid_labels(self, bad):
        with pytest.raises(ValueError):
            validate_session_labels([bad])
