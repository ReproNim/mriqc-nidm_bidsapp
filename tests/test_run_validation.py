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
        # The guard must not reject a valid dataset: MRIQC still gets invoked.
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

        with patch("src.run.MRIQCWrapper") as mock_wrapper:
            main()

        mock_wrapper.assert_called_once()
