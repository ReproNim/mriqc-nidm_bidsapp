"""
Tests that the CLI rejects malformed inputs before doing any work.

These guard the boundary between "the user pointed us at something usable" and
the rest of the pipeline. Getting this wrong is expensive in the BABS setting:
a subject-level job that starts MRIQC against a non-BIDS directory burns a
scheduler slot and fails deep inside the container, where the real cause is
buried in MRIQC's traceback rather than reported by us.
"""

import os
import sys
from unittest.mock import patch

import pytest

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


def _run_main(monkeypatch, bids_dir, out_dir, *options):
    """Run main() on a BIDS tree with MRIQC and the per-subject step mocked."""
    monkeypatch.setattr(
        sys, "argv", ["run.py", str(bids_dir), str(out_dir), "participant", *options]
    )
    with patch("src.run.MRIQCWrapper") as mock_wrapper, patch(
        "src.run.process_subject", return_value=True
    ) as mock_process:
        try:
            exit_code = main()
        except SystemExit as e:
            exit_code = e.code
    return exit_code, mock_wrapper, mock_process


not_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="root can search any directory"
)


class TestNidmInputDirValidation:
    """An explicit --nidm-input-dir must be a directory the lookup can use.

    Without the check, a directory that is not there (a typo, an unset
    variable, a missing bind mount) gives every subject a nidm.ttl without the
    input document, and the job exits 0.
    """

    def _assert_usage_error(self, capsys, result, out_dir, message):
        exit_code, mock_wrapper, mock_process = result
        err = capsys.readouterr().err
        assert exit_code == 2, err
        assert "--nidm-input-dir" in err
        assert message in err, err
        mock_wrapper.assert_not_called()
        mock_process.assert_not_called()
        # A usage error comes before anything is created.
        assert not out_dir.exists()

    @pytest.mark.parametrize("extra", [(), ("--skip-nidm-conversion",)])
    def test_rejects_what_is_not_a_directory(
        self, tmp_path, monkeypatch, capsys, extra
    ):
        bids_dir = _write_bids_tree(tmp_path / "bids")
        a_file = tmp_path / "nidm.ttl"
        a_file.write_text("")
        # Executable, so only the directory check can reject it.
        a_file.chmod(0o755)
        cases = (
            (tmp_path / "absent", "does not exist"),
            # A component of the path is a file (ENOTDIR).
            (a_file / "NIDM", "does not exist"),
            (a_file, "is not a directory"),
            ("/dev/null", "is not a directory"),
            # An unset variable in a wrapper; "." would be the working directory.
            ("", "must not be empty"),
            ("  ", "must not be empty"),
        )
        for bad, message in cases:
            out_dir = tmp_path / "out"
            result = _run_main(
                monkeypatch, bids_dir, out_dir, *extra, "--nidm-input-dir", str(bad)
            )
            self._assert_usage_error(capsys, result, out_dir, message)

    def test_rejects_an_empty_value_given_with_an_equals_sign(
        self, tmp_path, monkeypatch, capsys
    ):
        bids_dir = _write_bids_tree(tmp_path / "bids")
        out_dir = tmp_path / "out"
        result = _run_main(monkeypatch, bids_dir, out_dir, "--nidm-input-dir=")
        self._assert_usage_error(capsys, result, out_dir, "must not be empty")

    @not_root
    def test_rejects_a_directory_without_search_permission(
        self, tmp_path, monkeypatch, capsys
    ):
        # r-- can be listed but not searched; the per-subject lookup would
        # raise PermissionError in the middle of the run.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        out_dir = tmp_path / "out"
        locked = tmp_path / "read_only_nidm"
        locked.mkdir()
        (locked / "nidm.ttl").write_text("")
        locked.chmod(0o444)
        try:
            result = _run_main(
                monkeypatch, bids_dir, out_dir, "--nidm-input-dir", str(locked)
            )
        finally:
            locked.chmod(0o700)
        self._assert_usage_error(capsys, result, out_dir, "is not searchable")

    @not_root
    def test_names_the_cause_under_an_unsearchable_parent(
        self, tmp_path, monkeypatch, capsys
    ):
        # "does not exist" would send the operator after a typo.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        out_dir = tmp_path / "out"
        locked = tmp_path / "locked"
        (locked / "NIDM").mkdir(parents=True)
        (locked / "NIDM" / "nidm.ttl").write_text("")
        locked.chmod(0)
        try:
            result = _run_main(
                monkeypatch,
                bids_dir,
                out_dir,
                "--nidm-input-dir",
                str(locked / "NIDM"),
            )
        finally:
            locked.chmod(0o700)
        self._assert_usage_error(
            capsys, result, out_dir, "cannot be accessed: Permission denied"
        )

    def test_rejects_a_directory_with_no_entries(self, tmp_path, monkeypatch, capsys):
        # An uninstalled datalad subdataset or an empty mount.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        out_dir = tmp_path / "out"
        empty = tmp_path / "empty_nidm"
        empty.mkdir()
        result = _run_main(
            monkeypatch, bids_dir, out_dir, "--nidm-input-dir", str(empty)
        )
        self._assert_usage_error(capsys, result, out_dir, "is empty")

    def test_the_empty_directory_error_says_how_to_fix_it(
        self, tmp_path, monkeypatch, capsys
    ):
        bids_dir = _write_bids_tree(tmp_path / "bids")
        empty = tmp_path / "empty_nidm"
        empty.mkdir()
        _run_main(
            monkeypatch, bids_dir, tmp_path / "out", "--nidm-input-dir", str(empty)
        )
        err = capsys.readouterr().err
        assert "datalad get -n" in err
        assert "mounted" in err

    def test_accepts_a_directory_with_any_entry(self, tmp_path, monkeypatch):
        # Any entry counts, even one the lookup would not use for this subject.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        nidm = tmp_path / "nidm"
        (nidm / "sub-02").mkdir(parents=True)
        exit_code, mock_wrapper, mock_process = _run_main(
            monkeypatch,
            bids_dir,
            tmp_path / "out",
            "--skip-nidm-conversion",
            "--nidm-input-dir",
            str(nidm),
        )
        assert exit_code == 0
        mock_wrapper.assert_called_once()
        assert mock_process.call_args.kwargs["nidm_input_dir"] == nidm

    @not_root
    def test_accepts_a_directory_that_can_only_be_searched(
        self, tmp_path, monkeypatch
    ):
        # The lookup tries fixed paths under the directory and never lists it,
        # so search permission is enough.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        search_only = tmp_path / "search_only_nidm"
        search_only.mkdir()
        search_only.chmod(0o100)
        try:
            exit_code, mock_wrapper, mock_process = _run_main(
                monkeypatch,
                bids_dir,
                tmp_path / "out",
                "--skip-nidm-conversion",
                "--nidm-input-dir",
                str(search_only),
            )
        finally:
            search_only.chmod(0o700)
        assert exit_code == 0
        mock_wrapper.assert_called_once()
        assert mock_process.call_args.kwargs["nidm_input_dir"] == search_only

    def test_an_absent_default_directory_is_not_an_error(self, tmp_path, monkeypatch):
        # Without the flag the app looks in <bids_dir>/../NIDM, which need not
        # exist: the run then builds NIDM without an input document.
        bids_dir = _write_bids_tree(tmp_path / "bids")
        assert not (tmp_path / "NIDM").exists()
        exit_code, mock_wrapper, mock_process = _run_main(
            monkeypatch, bids_dir, tmp_path / "out", "--skip-nidm-conversion"
        )
        assert exit_code == 0
        mock_wrapper.assert_called_once()
        assert mock_process.call_args.kwargs["nidm_input_dir"] is None
