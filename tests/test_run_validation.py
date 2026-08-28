"""
Tests that the CLI rejects malformed inputs before doing any work.

These guard the boundary between "the user pointed us at something usable" and
the rest of the pipeline. Getting this wrong is expensive in the BABS setting:
a subject-level job that starts MRIQC against a non-BIDS directory burns a
scheduler slot and fails deep inside the container, where the real cause is
buried in MRIQC's traceback rather than reported by us.
"""

import sys
from unittest.mock import patch

from src.run import main


def _write_bids_tree(root, with_description=True, with_subject=True):
    """Build a minimal BIDS tree, optionally omitting required pieces."""
    root.mkdir(parents=True, exist_ok=True)
    if with_description:
        (root / "dataset_description.json").write_text(
            '{"Name": "test", "BIDSVersion": "1.8.0"}'
        )
    if with_subject:
        anat = root / "sub-01" / "anat"
        anat.mkdir(parents=True, exist_ok=True)
        (anat / "sub-01_T1w.nii.gz").write_bytes(b"")
    return root


class TestBidsDirectoryValidation:
    """The BIDS input must be a BIDS dataset, not merely a directory."""

    def test_rejects_bids_dir_missing_dataset_description(self, tmp_path, monkeypatch):
        # A directory with subjects but no dataset_description.json is not a
        # BIDS dataset. MRIQC must never be started against it.
        bids_dir = _write_bids_tree(tmp_path / "bids", with_description=False)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run.py",
                str(bids_dir),
                str(tmp_path / "out"),
                "participant",
                "--skip-nidm-conversion",
            ],
        )

        with patch("src.run.MRIQCWrapper") as mock_wrapper:
            exit_code = main()

        assert exit_code == 1
        mock_wrapper.assert_not_called()

    def test_accepts_well_formed_bids_dir(self, tmp_path, monkeypatch):
        # The guard must not reject a valid dataset. Assert the whole contract,
        # not just that the mock was touched: a run that reaches MRIQC but then
        # fails downstream still returns 1, so checking only "MRIQCWrapper was
        # constructed" would stay green over a broken pipeline.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run.py",
                str(bids_dir),
                str(tmp_path / "out"),
                "participant",
                "--skip-nidm-conversion",
            ],
        )

        with patch("src.run.MRIQCWrapper") as mock_wrapper, patch(
            "src.run.process_subject", return_value=True
        ):
            exit_code = main()

        assert exit_code == 0
        mock_wrapper.assert_called_once()


class TestOutputDirectoryValidation:
    """An unusable output directory must be reported, not raised."""

    def test_returns_error_when_output_dir_cannot_be_created(
        self, tmp_path, monkeypatch
    ):
        # A read-only parent (a full quota or a wrong mount under BABS) must
        # produce an exit code, not a PermissionError traceback from mkdir.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o555)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run.py",
                str(bids_dir),
                str(locked / "out"),
                "participant",
                "--skip-nidm-conversion",
            ],
        )

        try:
            with patch("src.run.MRIQCWrapper") as mock_wrapper:
                exit_code = main()
        finally:
            locked.chmod(0o755)

        assert exit_code == 1
        mock_wrapper.assert_not_called()
