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
from src.run import (
    _explicit_dwi_request,
    main,
    process_subject,
)
from src.utils import is_modalities_flag as _is_modalities_flag, parse_mriqc_args
from src.mriqc.mriqc_runner import MRIQCWrapper


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
        # In the dwi datatype directory, whatever the suffix.
        "sub-01/ses-1/dwi/sub-01_ses-1_run-1_sbref.json",
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
        # dwi not the last value.
        ["-m", "dwi", "T1w"],
        # Prefixes MRIQC reads as --modalities.
        ["--mo", "dwi"],
        ["--mod", "T1w", "dwi"],
        ["--modalitie", "dwi"],
        ["--mod=dwi"],
        ["--mo=dwi"],
        # Repeated: MRIQC keeps the last one, which asks for dwi.
        ["-m", "T1w", "--mod", "dwi"],
        ["--mod", "T1w", "-m", "dwi"],
        ["-m", "T1w", "-m", "dwi"],
        ["--modalities", "bold", "--nprocs", "2", "--mo=dwi"],
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
        # csv2nidm is never reached (the writer is mocked, so this call
        # count, not the absence of nidm.ttl, is the check).
        write.assert_not_called()
        assert len(_dwi_warnings(caplog)) == 1
        summary = json.loads((out / "sub-01" / "processing_summary.json").read_text())
        assert summary == {"dwi_iqms_not_converted": ["sub-01/dwi/sub-01_dwi.json"]}

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


class TestModalitiesSpelling:
    @pytest.mark.parametrize("arg", [
        "-m", "--mo", "--mod", "--modalitie", "--modalities",
        "--mod=dwi", "--modalities=T1w",
    ])
    def test_read_as_modalities(self, arg):
        assert _is_modalities_flag(arg)

    @pytest.mark.parametrize("arg", [
        # --m is ambiguous in MRIQC (--mem, --min-*-length).
        "--m", "--m=dwi", "--mem", "--mem-gb", "--min-dwi-length",
        "--modalitiesx", "--nprocs", "dwi", "-v",
    ])
    def test_not_read_as_modalities(self, arg):
        assert not _is_modalities_flag(arg)

    @pytest.mark.parametrize("extra", [
        # The last -m/--modalities wins in MRIQC, and it asks for no dwi.
        ["-m", "dwi", "--mod", "T1w"],
        ["--mod=dwi", "-m", "T1w", "bold"],
        ["-m", "dwi", "-m", "T1w"],
        # dwi as the value of another option.
        ["--min-dwi-length", "7"],
        ["--mem", "8", "-m", "T1w"],
    ])
    def test_not_an_explicit_request(self, extra):
        assert not _explicit_dwi_request(extra)

    def test_skip_mriqc_with_dwi_is_not_a_usage_error(
        self, tmp_path, monkeypatch, caplog
    ):
        # MRIQC is not run, so -m has no effect; dwi IQMs already in the
        # subject's mriqc/ are left out of the conversion instead.
        bids_dir, out_dir = _bids(tmp_path / "bids"), tmp_path / "out"
        existing = out_dir / "sub-01" / "mriqc" / "sub-01"
        _iqm_json(existing / "anat" / "sub-01_T1w.json")
        _iqm_json(existing / "dwi" / "sub-01_dwi.json")
        monkeypatch.setattr(sys, "argv", _argv(
            bids_dir, out_dir, "--skip-mriqc", "-m", "dwi"))
        with caplog.at_level(logging.INFO), \
                patch("src.run.MRIQCWrapper") as wrapper, \
                patch("src.run.check_csv2nidm_available", return_value=True), \
                patch("src.run._write_iqm_nidm") as write, \
                patch("src.run.check_iqm_records", return_value=[]):
            assert main() == 0
        wrapper.assert_not_called()
        assert [p.name for p in write.call_args.kwargs["csv_paths"]] == [
            "sub-01_T1w.csv"
        ]
        assert len(_dwi_warnings(caplog)) == 1


class TestProcessingSummary:
    def _run(self, tmp_path, rels, subject_dir):
        mriqc_dir = tmp_path / "mriqc"
        for rel in rels:
            _iqm_json(mriqc_dir / "sub-01" / rel)
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        with patch("src.run._write_iqm_nidm"), \
                patch("src.run.check_iqm_records", return_value=[]):
            return process_subject(
                subject_id="01", bids_dir=tmp_path / "bids", output_dir=out,
                subject_dir=subject_dir, mriqc_dir=mriqc_dir,
                session_id="1", nidm_input_dir=None,
                skip_mriqc=True, skip_nidm=False,
                logger=logging.getLogger("test-dwi"),
            )

    def test_mixed_subject_lists_the_dwi_iqms_beside_existing_entries(
        self, tmp_path
    ):
        subject_dir = tmp_path / "out" / "sub-01" / "ses-1"
        subject_dir.mkdir(parents=True)
        # As the --max-voxel-size gate writes it before MRIQC runs.
        gate = {"max_voxel_size": 2.0, "inputs_too_coarse": {},
                "inputs_not_checked": [], "modalities_not_run": []}
        (subject_dir / "processing_summary.json").write_text(json.dumps(gate))
        assert self._run(tmp_path, [
            "ses-1/anat/sub-01_ses-1_run-1_T1w.json",
            "ses-1/dwi/sub-01_ses-1_run-1_dwi.json",
            "ses-1/dwi/sub-01_ses-1_run-2_dwi.json",
        ], subject_dir) is True
        summary = json.loads((subject_dir / "processing_summary.json").read_text())
        assert summary == {**gate, "dwi_iqms_not_converted": [
            "sub-01/ses-1/dwi/sub-01_ses-1_run-1_dwi.json",
            "sub-01/ses-1/dwi/sub-01_ses-1_run-2_dwi.json",
        ]}

    def test_stale_entry_is_removed_when_no_dwi_is_left_out(self, tmp_path):
        subject_dir = tmp_path / "out" / "sub-01" / "ses-1"
        subject_dir.mkdir(parents=True)
        (subject_dir / "processing_summary.json").write_text(json.dumps(
            {"max_voxel_size": 2.0, "dwi_iqms_not_converted": ["old.json"]}))
        assert self._run(
            tmp_path, ["ses-1/anat/sub-01_ses-1_T1w.json"], subject_dir
        ) is True
        summary = json.loads((subject_dir / "processing_summary.json").read_text())
        assert summary == {"max_voxel_size": 2.0}

    def test_no_summary_without_dwi(self, tmp_path):
        subject_dir = tmp_path / "out" / "sub-01" / "ses-1"
        assert self._run(
            tmp_path, ["ses-1/anat/sub-01_ses-1_T1w.json"], subject_dir
        ) is True
        assert not (subject_dir / "processing_summary.json").exists()

    def test_summary_holding_only_a_stale_entry_is_removed(self, tmp_path):
        subject_dir = tmp_path / "out" / "sub-01" / "ses-1"
        subject_dir.mkdir(parents=True)
        (subject_dir / "processing_summary.json").write_text(json.dumps(
            {"dwi_iqms_not_converted": ["old.json"]}))
        assert self._run(
            tmp_path, ["ses-1/anat/sub-01_ses-1_T1w.json"], subject_dir
        ) is True
        assert not (subject_dir / "processing_summary.json").exists()


def _mriqc_replica():
    """MRIQC 25.0.0rc0's parser, as far as the modalities and the options
    sharing a prefix with them go (mriqc/cli/parser.py): -m/--modalities is
    store with nargs='*', and abbreviations are allowed."""
    import argparse

    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("bids_dir")
    p.add_argument("output_dir")
    p.add_argument("analysis_level")
    p.add_argument("-m", "--modalities", nargs="*",
                   choices=["T1w", "T2w", "bold", "dwi"])
    for opt in ("--mem", "--mem-gb", "--mem_gb", "--min-bold-length",
                "--min-dwi-length", "--nprocs", "-w", "--participant-label"):
        p.add_argument(opt)
    p.add_argument("--no-sub", action="store_true")
    p.add_argument("-v", action="count")
    return p


class TestCheckAgreesWithTheBuiltCommand:
    """The usage check judges the MRIQC command the app builds, read the
    way MRIQC reads it."""

    @pytest.mark.parametrize("extra", [
        ["-m", "dwi"],
        ["-m", "dwi", "T1w"],
        ["--mod", "dwi"],
        ["--mo=dwi"],
        ["-m", "T1w", "--mod", "dwi"],
        ["--mod", "T1w", "-m", "dwi"],
        ["-m", "dwi", "--mod", "T1w"],
        ["--mod=dwi", "-m", "T1w", "bold"],
        ["--mod", "dwi", "-m", "T1w"],
        ["--mo", "dwi", "--modalities", "T1w"],
        ["--mod", "dwi", "--modalities=T1w"],
        ["--mod", "T1w", "--mo", "dwi", "--mod", "bold"],
        ["--mod", "T1w", "--mo", "bold", "--mod", "dwi"],
        ["--modalities", "bold", "--nprocs", "2", "--mo=dwi"],
        ["-m", "T1w", "-m", "dwi"],
        ["-m", "dwi", "-m", "T1w"],
        ["--min-dwi-length", "7", "-m", "T1w"],
        ["--mem", "8", "--mod", "dwi"],
    ])
    def test_agreement(self, tmp_path, extra):
        # The constructor asks the mriqc executable for its version.
        with patch("src.mriqc.mriqc_runner.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "MRIQC v25.0.0rc0\n"
            wrapper = MRIQCWrapper(
                bids_dir=tmp_path / "bids", output_dir=tmp_path / "out"
            )
        cmd = wrapper._create_mriqc_command(
            output_dir=tmp_path / "out", subject_id="01", **parse_mriqc_args(extra)
        )
        assert cmd[0] == "mriqc"
        ns, _ = _mriqc_replica().parse_known_args(cmd[1:])
        mriqc_rates_dwi_only_on_request = "dwi" in (ns.modalities or [])
        assert _explicit_dwi_request(extra) == mriqc_rates_dwi_only_on_request
        # One -m at most, and no abbreviation left for MRIQC to resolve.
        assert cmd.count("-m") <= 1
        assert not [a for a in cmd if a.startswith("--mo")]


class TestUnreadableProcessingSummary:
    @pytest.mark.parametrize("content", ["", '{"max_voxel_size": 2.0, "inputs_too', "[1, 2]"])
    def test_skip_mriqc_without_dwi_converts_and_keeps_the_file(
        self, tmp_path, monkeypatch, caplog, content
    ):
        bids_dir, out_dir = _bids(tmp_path / "bids"), tmp_path / "out"
        _iqm_json(out_dir / "sub-01" / "mriqc" / "sub-01" / "anat" / "sub-01_T1w.json")
        summary_file = out_dir / "sub-01" / "processing_summary.json"
        summary_file.write_text(content)
        monkeypatch.setattr(sys, "argv", _argv(bids_dir, out_dir, "--skip-mriqc"))
        with caplog.at_level(logging.INFO), \
                patch("src.run.check_csv2nidm_available", return_value=True), \
                patch("src.run._write_iqm_nidm") as write, \
                patch("src.run.check_iqm_records", return_value=[]):
            assert main() == 0
        write.assert_called_once()
        assert summary_file.read_text() == content
        assert [r for r in caplog.records
                if r.levelno == logging.WARNING and "Ignoring unreadable" in r.getMessage()]

    def test_with_dwi_is_replaced_by_the_dwi_entry(self, tmp_path, caplog):
        mriqc_dir = tmp_path / "mriqc"
        _iqm_json(mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json")
        _iqm_json(mriqc_dir / "sub-01" / "dwi" / "sub-01_dwi.json")
        subject_dir = tmp_path / "out" / "sub-01"
        subject_dir.mkdir(parents=True)
        (subject_dir / "processing_summary.json").write_text('{"max_vox')
        with caplog.at_level(logging.INFO), \
                patch("src.run._write_iqm_nidm"), \
                patch("src.run.check_iqm_records", return_value=[]):
            assert process_subject(
                subject_id="01", bids_dir=tmp_path / "bids",
                output_dir=tmp_path / "out", subject_dir=subject_dir,
                mriqc_dir=mriqc_dir, session_id=None, nidm_input_dir=None,
                skip_mriqc=True, skip_nidm=False,
                logger=logging.getLogger("test-dwi"),
            ) is True
        assert json.loads((subject_dir / "processing_summary.json").read_text()) == {
            "dwi_iqms_not_converted": ["sub-01/dwi/sub-01_dwi.json"]
        }
