"""
Tests for main()'s orchestration: argument handling, subject selection, and the
exit codes that BABS reads.

Exit codes matter operationally here. A BABS array job treats a non-zero return
as a failed subject, so "partially succeeded" must not look like success, and a
misconfigured run must fail before it consumes a scheduler slot.
"""

import sys
from unittest.mock import patch

import pytest

from src.run import main


def _bids(root, subjects=("01",)):
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        '{"Name": "test", "BIDSVersion": "1.8.0"}'
    )
    for sub in subjects:
        (root / f"sub-{sub}" / "anat").mkdir(parents=True, exist_ok=True)
    return root


def _argv(bids_dir, out_dir, *extra):
    return ["run.py", str(bids_dir), str(out_dir), "participant", *extra]


@pytest.fixture
def dataset(tmp_path):
    return _bids(tmp_path / "bids"), tmp_path / "out"


class TestSessionLabel:
    def test_rejects_more_than_one_session_label(self, dataset, monkeypatch):
        # The session determines the output directory, so two of them have no
        # single correct answer. Fail rather than silently pick one.
        bids_dir, out_dir = dataset
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, out_dir, "--session-label", "a", "b",
                  "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper") as wrapper:
            assert main() == 1
        wrapper.assert_not_called()

    @pytest.mark.parametrize("given", ["baseline", "ses-baseline"])
    def test_single_session_label_is_normalised_and_reaches_the_pipeline(
        self, dataset, monkeypatch, given
    ):
        # Asserting only `main() == 0` would not notice the session being
        # dropped: with session_id=None every session of a subject writes to
        # the same sub-<id>/nidm.ttl and silently overwrites the previous one,
        # while the run still reports success. BABS session-level jobs always
        # pass --session-label, so the label must survive normalisation and
        # reach both MRIQC and the NIDM conversion.
        bids_dir, out_dir = dataset
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, out_dir, "--session-label", given,
                  "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.process_subject", return_value=True) as proc:
            assert main() == 0

        assert proc.call_args.kwargs["session_id"] == "baseline"
        assert wrapper.return_value.process_participant.call_args.kwargs[
            "session_id"
        ] == "baseline"


class TestSubjectSelection:
    @pytest.mark.parametrize("given", ["01", "sub-01"])
    def test_participant_label_accepts_both_prefixed_and_bare(
        self, dataset, monkeypatch, given
    ):
        # BABS passes sub-<id>; humans usually pass the bare id. Both must
        # resolve to the same subject.
        bids_dir, out_dir = dataset
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, out_dir, "--participant-label", given,
                  "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.process_subject", return_value=True) as proc:
            assert main() == 0
        assert proc.call_args.kwargs["subject_id"] == "01"
        assert wrapper.return_value.process_participant.call_args.kwargs[
            "subject_id"
        ] == "01"

    def test_discovers_all_subjects_when_no_label_given(self, tmp_path, monkeypatch):
        bids_dir = _bids(tmp_path / "bids", subjects=("01", "02", "03"))
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, tmp_path / "out", "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper"), \
                patch("src.run.process_subject", return_value=True) as proc:
            assert main() == 0
        assert [c.kwargs["subject_id"] for c in proc.call_args_list] == [
            "01", "02", "03",
        ]


class TestSkipMriqc:
    def test_errors_when_existing_mriqc_output_is_absent(self, dataset, monkeypatch):
        # --skip-mriqc promises the results are already there. If they are not,
        # say so instead of producing an empty derivative.
        bids_dir, out_dir = dataset
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, out_dir, "--skip-mriqc", "--skip-nidm-conversion"),
        )
        with patch("src.run.process_subject") as proc:
            assert main() == 1
        proc.assert_not_called()

    def test_does_not_invoke_mriqc_when_output_exists(self, dataset, monkeypatch):
        bids_dir, out_dir = dataset
        (out_dir / "sub-01" / "mriqc").mkdir(parents=True)
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, out_dir, "--skip-mriqc", "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.process_subject", return_value=True):
            assert main() == 0
        wrapper.assert_not_called()


class TestExitCodes:
    def test_returns_zero_when_every_subject_succeeds(self, tmp_path, monkeypatch):
        bids_dir = _bids(tmp_path / "bids", subjects=("01", "02"))
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, tmp_path / "out", "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper"), \
                patch("src.run.process_subject", return_value=True):
            assert main() == 0

    def test_returns_one_when_every_subject_fails(self, tmp_path, monkeypatch):
        bids_dir = _bids(tmp_path / "bids", subjects=("01", "02"))
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, tmp_path / "out", "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper"), \
                patch("src.run.process_subject", return_value=False):
            assert main() == 1

    def test_partial_success_is_not_reported_as_success(self, tmp_path, monkeypatch):
        # One of two subjects failing must not return 0: BABS would record the
        # job as clean and the missing subject would go unnoticed.
        bids_dir = _bids(tmp_path / "bids", subjects=("01", "02"))
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, tmp_path / "out", "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper"), \
                patch("src.run.process_subject", side_effect=[True, False]):
            assert main() == 1


class TestRequiredTools:
    def test_errors_when_csv2nidm_missing_and_conversion_requested(
        self, dataset, monkeypatch
    ):
        bids_dir, out_dir = dataset
        monkeypatch.setattr(sys, "argv", _argv(bids_dir, out_dir))
        with patch("src.run.check_csv2nidm_available", return_value=False), \
                patch("src.run.MRIQCWrapper") as wrapper:
            assert main() == 1
        wrapper.assert_not_called()

    def test_missing_csv2nidm_is_tolerated_when_conversion_skipped(
        self, dataset, monkeypatch
    ):
        bids_dir, out_dir = dataset
        monkeypatch.setattr(
            sys, "argv", _argv(bids_dir, out_dir, "--skip-nidm-conversion")
        )
        with patch("src.run.check_csv2nidm_available", return_value=False), \
                patch("src.run.MRIQCWrapper"), \
                patch("src.run.process_subject", return_value=True):
            assert main() == 0


class TestMriqcFailureHandling:
    def test_mriqc_construction_failure_returns_one(self, dataset, monkeypatch):
        bids_dir, out_dir = dataset
        monkeypatch.setattr(
            sys, "argv", _argv(bids_dir, out_dir, "--skip-nidm-conversion")
        )
        with patch("src.run.MRIQCWrapper", side_effect=RuntimeError("boom")), \
                patch("src.run.process_subject") as proc:
            assert main() == 1
        proc.assert_not_called()

    def test_single_subject_mriqc_failure_does_not_abort_the_run(
        self, tmp_path, monkeypatch
    ):
        # One subject's MRIQC blowing up must not stop the others; the loop
        # logs and continues.
        bids_dir = _bids(tmp_path / "bids", subjects=("01", "02"))
        monkeypatch.setattr(
            sys, "argv",
            _argv(bids_dir, tmp_path / "out", "--skip-nidm-conversion"),
        )
        with patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.process_subject", return_value=True) as proc:
            wrapper.return_value.process_participant.side_effect = [
                RuntimeError("sub-01 failed"), None
            ]
            assert main() == 0
        assert proc.call_count == 2
