"""
dwi IQMs never reach csv2nidm.

The MRIQC IQM data dictionary has no dwi metrics. csv2nidm, given a column the
dictionary does not describe, asks for an annotation on standard input; in a
batch job that is EOF, and no nidm.ttl is written. So an explicit dwi request
is refused before MRIQC runs, and dwi IQM JSONs found in the MRIQC output
(MRIQC run without -m, a reused --mriqc-output-dir) are left out of the
conversion with one warning.
"""

import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.mriqc.mriqc_runner import is_dwi_iqm_json
from src.run import main, process_subject


def _bids(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        '{"Name": "test", "BIDSVersion": "1.8.0"}'
    )
    (root / "sub-01" / "anat").mkdir(parents=True, exist_ok=True)
    return root


def _argv(bids_dir, out_dir, *extra):
    return ["run.py", str(bids_dir), str(out_dir), "participant", *extra]


def _iqm_json(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "bids_meta": {"subject": "01"},
        "provenance": {"software": "mriqc", "version": "25.0.0"},
        "efc": 0.5,
        "fd_mean": 0.1,
    }))
    return path


# (anat, func, dwi) paths below sub-01/, and the session to pass, for layouts
# with and without sessions and runs.
LAYOUTS = {
    "plain": (
        "anat/sub-01_T1w.json",
        "func/sub-01_task-rest_bold.json",
        "dwi/sub-01_dwi.json",
        None,
    ),
    "run": (
        "anat/sub-01_run-1_T1w.json",
        "func/sub-01_task-rest_run-2_bold.json",
        "dwi/sub-01_acq-b1000_run-1_dwi.json",
        None,
    ),
    "session_unpinned": (
        "ses-1/anat/sub-01_ses-1_T1w.json",
        "ses-1/func/sub-01_ses-1_task-rest_bold.json",
        "ses-1/dwi/sub-01_ses-1_run-1_dwi.json",
        None,
    ),
    "session_pinned": (
        "ses-1/anat/sub-01_ses-1_run-1_T1w.json",
        "ses-1/func/sub-01_ses-1_task-rest_run-1_bold.json",
        "ses-1/dwi/sub-01_ses-1_dir-AP_run-2_dwi.json",
        "1",
    ),
}


def _dwi_warnings(caplog):
    return [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "dwi IQM" in r.getMessage()
    ]


class TestIsDwiIqmJson:
    @pytest.mark.parametrize("path", [
        "sub-01/dwi/sub-01_dwi.json",
        "sub-01/ses-1/dwi/sub-01_ses-1_run-1_dwi.json",
        "sub-01/ses-1/dwi/sub-01_ses-1_acq-b1000_dir-AP_run-2_dwi.json",
        # Out of its datatype directory, the suffix still marks it.
        "flat/sub-01_ses-1_run-1_dwi.json",
    ])
    def test_dwi(self, path):
        assert is_dwi_iqm_json(Path(path))

    @pytest.mark.parametrize("path", [
        "sub-01/anat/sub-01_T1w.json",
        "sub-01/ses-1/anat/sub-01_ses-1_run-1_T2w.json",
        "sub-01/ses-1/func/sub-01_ses-1_task-rest_run-1_bold.json",
        # dwi as an entity label, not the suffix or the directory.
        "sub-dwi/anat/sub-dwi_T1w.json",
        "sub-01/func/sub-01_task-dwi_bold.json",
        "sub-01/ses-dwi/anat/sub-01_ses-dwi_T1w.json",
    ])
    def test_not_dwi(self, path):
        assert not is_dwi_iqm_json(Path(path))


class TestExplicitDwiRequest:
    @pytest.mark.parametrize("modalities", [
        ["-m", "dwi"],
        ["-m", "T1w", "dwi"],
        ["--modalities", "T1w", "bold", "dwi"],
        ["--modalities=dwi"],
    ])
    def test_is_a_usage_error_with_nidm_conversion(
        self, tmp_path, monkeypatch, capsys, modalities
    ):
        bids_dir, out_dir = _bids(tmp_path / "bids"), tmp_path / "out"
        monkeypatch.setattr(sys, "argv", _argv(bids_dir, out_dir, *modalities))
        with patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.process_subject") as proc:
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
        wrapper.assert_not_called()
        proc.assert_not_called()
        err = capsys.readouterr().err
        assert "dwi IQMs cannot be converted to NIDM yet" in err
        assert "--skip-nidm-conversion" in err
        # Refused before anything is created.
        assert not out_dir.exists()

    def test_is_allowed_with_skip_nidm_conversion(self, tmp_path, monkeypatch):
        bids_dir, out_dir = _bids(tmp_path / "bids"), tmp_path / "out"
        monkeypatch.setattr(sys, "argv", _argv(
            bids_dir, out_dir, "--skip-nidm-conversion", "-m", "T1w", "dwi"))
        with patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.process_subject", return_value=True):
            assert main() == 0
        kwargs = wrapper.return_value.process_participant.call_args.kwargs
        assert kwargs["modalities"] == ["T1w", "dwi"]

    @pytest.mark.parametrize("modalities", [[], ["-m", "T1w", "bold"], ["-m"]])
    def test_other_requests_run_mriqc(self, tmp_path, monkeypatch, modalities):
        # No -m (MRIQC's default, dwi included), a list without dwi, and a
        # bare -m are not refused.
        bids_dir, out_dir = _bids(tmp_path / "bids"), tmp_path / "out"
        monkeypatch.setattr(sys, "argv", _argv(bids_dir, out_dir, *modalities))
        with patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.check_csv2nidm_available", return_value=True), \
                patch("src.run.process_subject", return_value=True):
            assert main() == 0
        wrapper.return_value.process_participant.assert_called_once()


class TestDwiIqmsLeftOut:
    @pytest.mark.parametrize("layout", sorted(LAYOUTS))
    def test_dwi_is_excluded_and_the_rest_converted(
        self, tmp_path, caplog, layout
    ):
        anat, func, dwi, session_id = LAYOUTS[layout]
        mriqc_dir = tmp_path / "mriqc"
        for rel in (anat, func, dwi):
            _iqm_json(mriqc_dir / "sub-01" / rel)
        out = tmp_path / "out"
        out.mkdir()
        subject_dir = out / "sub-01"
        if session_id:
            subject_dir = subject_dir / f"ses-{session_id}"

        with caplog.at_level(logging.INFO), \
                patch("src.run._write_iqm_nidm") as write, \
                patch("src.run.check_iqm_records", return_value=[]) as check:
            assert process_subject(
                subject_id="01", bids_dir=tmp_path / "bids", output_dir=out,
                subject_dir=subject_dir, mriqc_dir=mriqc_dir,
                session_id=session_id, nidm_input_dir=None,
                skip_mriqc=True, skip_nidm=False,
                logger=logging.getLogger("test-dwi"),
            ) is True

        # Only the anat and func rows reach csv2nidm.
        converted = sorted(p.name for p in write.call_args.kwargs["csv_paths"])
        assert converted == sorted(
            Path(rel).stem + ".csv" for rel in (anat, func)
        )
        assert sorted(p.name for p in check.call_args.args[1]) == sorted(
            Path(rel).name for rel in (anat, func)
        )
        warnings = _dwi_warnings(caplog)
        assert len(warnings) == 1
        assert Path(dwi).name in warnings[0].getMessage()
        assert "cannot be converted to NIDM" in warnings[0].getMessage()

    def test_only_dwi_fails_the_subject_without_calling_csv2nidm(
        self, tmp_path, caplog
    ):
        mriqc_dir = tmp_path / "mriqc"
        _iqm_json(mriqc_dir / "sub-01" / "dwi" / "sub-01_dwi.json")
        out = tmp_path / "out"
        out.mkdir()
        with caplog.at_level(logging.INFO), \
                patch("src.run._write_iqm_nidm") as write:
            assert process_subject(
                subject_id="01", bids_dir=tmp_path / "bids", output_dir=out,
                subject_dir=out / "sub-01", mriqc_dir=mriqc_dir,
                session_id=None, nidm_input_dir=None,
                skip_mriqc=True, skip_nidm=False,
                logger=logging.getLogger("test-dwi"),
            ) is False
        write.assert_not_called()
        assert not (out / "sub-01" / "nidm.ttl").exists()
        assert len(_dwi_warnings(caplog)) == 1

    def test_no_warning_with_skip_nidm(self, tmp_path, caplog):
        mriqc_dir = tmp_path / "mriqc"
        _iqm_json(mriqc_dir / "sub-01" / "dwi" / "sub-01_dwi.json")
        _iqm_json(mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json")
        out = tmp_path / "out"
        out.mkdir()
        with caplog.at_level(logging.INFO):
            assert process_subject(
                subject_id="01", bids_dir=tmp_path / "bids", output_dir=out,
                subject_dir=out / "sub-01", mriqc_dir=mriqc_dir,
                session_id=None, nidm_input_dir=None,
                skip_mriqc=True, skip_nidm=True,
                logger=logging.getLogger("test-dwi"),
            ) is True
        assert not _dwi_warnings(caplog)

    @pytest.mark.parametrize("session", [None, "1"])
    def test_reused_mriqc_output_dir(self, tmp_path, monkeypatch, caplog, session):
        # A standard MRIQC tree passed with --mriqc-output-dir: -m does not
        # apply (MRIQC is not run), and its dwi IQMs are still left out.
        bids_dir, out_dir = _bids(tmp_path / "bids"), tmp_path / "out"
        existing = tmp_path / "existing_mriqc" / "sub-01"
        ses = f"ses-{session}/" if session else ""
        ent = f"_ses-{session}" if session else ""
        _iqm_json(existing / f"{ses}anat/sub-01{ent}_run-1_T1w.json")
        _iqm_json(existing / f"{ses}dwi/sub-01{ent}_run-1_dwi.json")
        extra = ["--mriqc-output-dir", str(existing.parent), "-m", "dwi"]
        if session:
            extra += ["--session-label", session]
        monkeypatch.setattr(sys, "argv", _argv(bids_dir, out_dir, *extra))
        with caplog.at_level(logging.INFO), \
                patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.check_csv2nidm_available", return_value=True), \
                patch("src.run._write_iqm_nidm") as write, \
                patch("src.run.check_iqm_records", return_value=[]):
            assert main() == 0
        wrapper.assert_not_called()
        assert [p.name for p in write.call_args.kwargs["csv_paths"]] == [
            f"sub-01{ent}_run-1_T1w.csv"
        ]
        warnings = _dwi_warnings(caplog)
        assert len(warnings) == 1
        assert f"sub-01{ent}_run-1_dwi.json" in warnings[0].getMessage()
