"""
Tests for the --max-voxel-size gate on anatomical inputs (src/mriqc/inputs.py)
and how main() hands it to MRIQC.

The case behind it: ABIDE II UCLA_Long sessions hold a 1 mm T1w and a
1.5 x 1.5 x 4 mm ``acq-hires`` slab. MRIQC crashes on the slab and the whole
session fails, so the slab must never reach MRIQC while the 1 mm image and the
functional runs still do.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import nibabel as nib
import numpy as np
import pytest
from bids import BIDSLayout
from bids.layout import Query

from src.mriqc.inputs import gate_anat_inputs, selecting_filter
from src.mriqc.mriqc_runner import MRIQCWrapper
from src.run import main

FINE = (1.2, 1.0, 1.0)
SLAB = (1.5, 1.5, 4.0)


def _image(path: Path, zooms):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.zeros((4, 4, 4), dtype=np.int16),
                             np.diag([*zooms, 1.0])), str(path))
    return path


def _bids(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        '{"Name": "test", "BIDSVersion": "1.8.0"}'
    )
    return root


def _anat(root, name, zooms, sub="01", ses="1"):
    return _image(root / f"sub-{sub}" / f"ses-{ses}" / "anat" / name, zooms)


def _mriqc_selects(bids_dir, subject, session, suffix, query):
    """What MRIQC 25 selects: niworkflows collect_data's query plus the filter."""
    layout = BIDSLayout(str(bids_dir), validate=False)
    base = {"datatype": "anat", "suffix": suffix, "part": ["mag", None]}
    get_kwargs = {"return_type": "file", "subject": subject,
                  "session": session or Query.OPTIONAL,
                  "extension": [".nii", ".nii.gz"]}
    # The filter overrides both, as in collect_data.
    return sorted(Path(f).name for f in layout.get(**{**get_kwargs, **base, **query}))


@pytest.fixture
def ucla(tmp_path):
    """One session with a 1 mm T1w and a 4 mm acq-hires slab."""
    bids = _bids(tmp_path / "bids")
    fine = _anat(bids, "sub-01_ses-1_run-1_T1w.nii.gz", FINE)
    slab = _anat(bids, "sub-01_ses-1_acq-hires_run-1_T1w.nii.gz", SLAB)
    return bids, fine, slab


class TestGate:
    def test_slab_is_filtered_out_and_the_1mm_image_kept(self, ucla):
        bids, fine, slab = ucla
        gate = gate_anat_inputs(bids, "01", "1", 2.0)

        assert gate.dropped == []
        assert [p for p, _ in gate.too_coarse] == [slab]
        assert gate.too_coarse[0][1] == SLAB
        # The filter is only as good as pybids' reading of it.
        assert _mriqc_selects(bids, "01", "1", "T1w", gate.filters["t1w"]) == [fine.name]

    def test_filter_is_json_that_pybids_reads_back_the_same(self, ucla):
        # MRIQC reads the filter from a JSON file: None must survive as null
        # and run as a plain integer.
        bids, fine, _ = ucla
        query = json.loads(json.dumps(gate_anat_inputs(bids, "01", "1", 2.0).filters))
        assert _mriqc_selects(bids, "01", "1", "T1w", query["t1w"]) == [fine.name]

    def test_a_session_with_only_the_slab_drops_the_modality(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_acq-hires_run-1_T1w.nii.gz", SLAB)
        gate = gate_anat_inputs(bids, "01", "1", 2.0)
        assert gate.dropped == ["T1w"]
        assert gate.filters == {}

    def test_nothing_changes_when_every_image_is_fine(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_T1w.nii.gz", FINE)
        _anat(bids, "sub-01_ses-1_T2w.nii.gz", (1.0, 1.0, 1.0))
        assert gate_anat_inputs(bids, "01", "1", 2.0) == ({}, [], [])

    def test_limit_is_inclusive(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_T1w.nii.gz", (2.0, 2.0, 2.0))
        assert gate_anat_inputs(bids, "01", "1", 2.0).too_coarse == []

    def test_t2w_is_gated_independently_of_t1w(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_T1w.nii.gz", FINE)
        _anat(bids, "sub-01_ses-1_T2w.nii.gz", SLAB)
        gate = gate_anat_inputs(bids, "01", "1", 2.0)
        assert gate.dropped == ["T2w"]
        assert gate.filters == {}

    def test_without_a_session_every_session_is_gated(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        fine = _anat(bids, "sub-01_ses-2_T1w.nii.gz", FINE, ses="2")
        _anat(bids, "sub-01_ses-1_acq-hires_T1w.nii.gz", SLAB, ses="1")
        gate = gate_anat_inputs(bids, "01", None, 2.0)
        assert _mriqc_selects(bids, "01", None, "T1w", gate.filters["t1w"]) == [fine.name]

    def test_without_a_session_sessions_named_alike_are_told_apart_by_session(
        self, tmp_path
    ):
        # Only the session differs, so only a session filter separates them;
        # MRIQC accepts one when it was not given --session-id.
        bids = _bids(tmp_path / "bids")
        fine = _anat(bids, "sub-01_ses-1_T1w.nii.gz", FINE, ses="1")
        _anat(bids, "sub-01_ses-2_T1w.nii.gz", SLAB, ses="2")
        gate = gate_anat_inputs(bids, "01", None, 2.0)
        assert _mriqc_selects(bids, "01", None, "T1w", gate.filters["t1w"]) == [fine.name]

    def test_unrequested_modalities_are_not_gated(self, ucla):
        bids, _, _ = ucla
        assert gate_anat_inputs(bids, "01", "1", 2.0, modalities=["bold"]) == ({}, [], [])

    def test_directory_names_above_the_dataset_do_not_become_entities(self, tmp_path):
        # The derivatives patterns (res-, desc-, ...) are not anchored to the
        # file name; MRIQC's layout does not use them and rejects the entity.
        bids = _bids(tmp_path / "features-x" / "res-2" / "bids")
        _anat(bids, "sub-01_ses-1_run-1_T1w.nii.gz", FINE)
        _anat(bids, "sub-01_ses-1_acq-hires_run-1_T1w.nii.gz", SLAB)
        query = gate_anat_inputs(bids, "01", "1", 2.0).filters["t1w"]
        assert set(query) == {"acquisition", "run"}

    @pytest.mark.parametrize("user_run", [1, "1", "01", [1]])
    def test_user_filter_narrows_and_is_read_as_pybids_reads_it(self, tmp_path, user_run):
        # "1", "01" and 1 all mean run 1 to pybids; comparing values by hand
        # once turned them into an empty list, which pybids reads as "any".
        bids = _bids(tmp_path / "bids")
        fine = _anat(bids, "sub-01_ses-1_run-01_T1w.nii.gz", FINE)
        _anat(bids, "sub-01_ses-1_run-02_T1w.nii.gz", FINE)
        _anat(bids, "sub-01_ses-1_acq-hires_run-01_T1w.nii.gz", SLAB)
        gate = gate_anat_inputs(bids, "01", "1", 2.0, user_filters={"t1w": {"run": user_run}})
        assert _mriqc_selects(bids, "01", "1", "T1w", gate.filters["t1w"]) == [fine.name]

    def test_user_filter_choosing_only_the_slab_drops_the_modality(self, ucla):
        bids, _, slab = ucla
        gate = gate_anat_inputs(
            bids, "01", "1", 2.0, user_filters={"t1w": {"acquisition": "hires"}})
        assert gate.dropped == ["T1w"]
        assert gate.filters == {}
        assert [p for p, _ in gate.too_coarse] == [slab]

    def test_user_filter_excluding_the_slab_needs_no_gate(self, ucla):
        bids, _, _ = ucla
        gate = gate_anat_inputs(
            bids, "01", "1", 2.0, user_filters={"t1w": {"acquisition": None}})
        assert gate == ({}, [], [])

    def test_phase_images_are_not_gated(self, tmp_path):
        # MRIQC never rates part-phase images, so a coarse one changes nothing.
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_part-mag_T1w.nii.gz", FINE)
        _anat(bids, "sub-01_ses-1_part-phase_T1w.nii.gz", SLAB)
        assert gate_anat_inputs(bids, "01", "1", 2.0) == ({}, [], [])

    def test_unreadable_header_is_left_for_mriqc(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_acq-hires_T1w.nii.gz", SLAB)
        broken = bids / "sub-01" / "ses-1" / "anat" / "sub-01_ses-1_T1w.nii.gz"
        broken.write_bytes(b"not a nifti")
        gate = gate_anat_inputs(bids, "01", "1", 2.0)
        assert gate.dropped == []
        assert _mriqc_selects(bids, "01", "1", "T1w", gate.filters["t1w"]) == [broken.name]

    def test_images_no_filter_can_separate_are_an_error(self, tmp_path):
        # Kept acq-a_run-1 and acq-b_run-2 allow acq in {a, b} and run in
        # {1, 2}, which also selects the dropped acq-a_run-2.
        anat = tmp_path / "sub-01" / "anat"
        keep = [anat / "sub-01_acq-a_run-1_T1w.nii.gz", anat / "sub-01_acq-b_run-2_T1w.nii.gz"]
        drop = [anat / "sub-01_acq-a_run-2_T1w.nii.gz"]
        with pytest.raises(ValueError, match="acq-a_run-2"):
            selecting_filter(keep, drop)


class TestMain:
    """main() passes the gate to MRIQC; subprocess.run stands in for MRIQC."""

    def _run(self, bids, out, *extra, writes_iqms=True):
        calls = []

        def fake_mriqc(cmd, **kwargs):
            calls.append(cmd)
            if writes_iqms:
                anat = Path(cmd[2]) / "sub-01" / "ses-1" / "anat"
                anat.mkdir(parents=True, exist_ok=True)
                (anat / "sub-01_ses-1_run-1_T1w.json").write_text('{"cjv": 0.4}')
            return subprocess.CompletedProcess(cmd, 0, "", "")

        argv = ["run.py", str(bids), str(out), "participant",
                "--participant-label", "01", "--session-label", "1",
                "--skip-nidm-conversion", *extra]
        with patch.object(sys, "argv", argv), \
                patch.object(MRIQCWrapper, "_get_mriqc_version", return_value="25.0.0rc0"), \
                patch("src.mriqc.mriqc_runner.subprocess.run", side_effect=fake_mriqc):
            code = main()
        return code, calls

    @staticmethod
    def _option(cmd, flag):
        return cmd[cmd.index(flag) + 1]

    def test_mriqc_gets_a_filter_without_the_slab(self, ucla, tmp_path):
        bids, fine, slab = ucla
        code, calls = self._run(bids, tmp_path / "out")
        assert code == 0
        [cmd] = calls
        filters = json.loads(Path(self._option(cmd, "--bids-filter-file")).read_text())
        assert _mriqc_selects(bids, "01", "1", "T1w", filters["t1w"]) == [fine.name]
        assert "-m" not in cmd
        # The filter file is scratch, not part of the subject's zip.
        assert "sub-01" not in Path(self._option(cmd, "--bids-filter-file")).parent.parts

        summary = json.loads(
            (tmp_path / "out" / "sub-01" / "ses-1" / "processing_summary.json").read_text())
        assert summary["max_voxel_size"] == 2.0
        assert summary["inputs_too_coarse"] == {
            slab.relative_to(bids).as_posix(): list(SLAB)}
        assert summary["modalities_not_run"] == []

    def test_no_filter_when_nothing_is_too_coarse(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_run-1_T1w.nii.gz", FINE)
        code, [cmd] = self._run(bids, tmp_path / "out")
        assert code == 0
        assert "--bids-filter-file" not in cmd and "-m" not in cmd

    def test_slab_only_session_runs_the_other_modalities(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_acq-hires_run-1_T1w.nii.gz", SLAB)
        code, [cmd] = self._run(bids, tmp_path / "out")
        assert code == 0
        i = cmd.index("-m")
        assert cmd[i + 1:i + 4] == ["T2w", "bold", "dwi"]
        assert cmd.count("-m") == 1

    def test_nothing_left_to_run_fails_before_mriqc(self, tmp_path):
        bids = _bids(tmp_path / "bids")
        _anat(bids, "sub-01_ses-1_acq-hires_run-1_T1w.nii.gz", SLAB)
        code, calls = self._run(bids, tmp_path / "out", "--modalities", "T1w")
        assert code == 1
        assert calls == []

    def test_a_larger_limit_lets_the_slab_through(self, ucla, tmp_path):
        bids, _, _ = ucla
        code, [cmd] = self._run(bids, tmp_path / "out", "--max-voxel-size", "4")
        assert code == 0
        assert "--bids-filter-file" not in cmd

    def test_user_filter_with_an_equals_sign_is_still_merged(self, ucla, tmp_path):
        bids, fine, _ = ucla
        user = tmp_path / "user_filter.json"
        user.write_text(json.dumps({"bold": {"task": "rest"}}))
        code, [cmd] = self._run(bids, tmp_path / "out", f"--bids-filter-file={user}")
        assert code == 0
        assert cmd.count("--bids-filter-file") == 1
        filters = json.loads(Path(self._option(cmd, "--bids-filter-file")).read_text())
        assert filters["bold"] == {"task": "rest"}
        assert _mriqc_selects(bids, "01", "1", "T1w", filters["t1w"]) == [fine.name]

    @pytest.mark.parametrize("flag", ["-m", "--modalities"])
    def test_requested_modalities_all_reach_mriqc(self, ucla, tmp_path, flag):
        bids, _, _ = ucla
        code, [cmd] = self._run(bids, tmp_path / "out", flag, "T1w", "bold")
        assert code == 0
        i = cmd.index("-m")
        assert cmd[i + 1:i + 3] == ["T1w", "bold"]
        assert cmd.count("-m") == 1 and "--modalities" not in cmd

    def test_user_filter_is_kept_and_narrowed(self, ucla, tmp_path):
        bids, fine, _ = ucla
        _anat(bids, "sub-01_ses-1_run-2_T1w.nii.gz", FINE)
        user = tmp_path / "user_filter.json"
        user.write_text(json.dumps({"T1w": {"run": 1}, "bold": {"task": "rest"}}))
        code, [cmd] = self._run(bids, tmp_path / "out", "--bids-filter-file", str(user))
        assert code == 0
        filters = json.loads(Path(self._option(cmd, "--bids-filter-file")).read_text())
        assert filters["bold"] == {"task": "rest"}
        assert _mriqc_selects(bids, "01", "1", "T1w", filters["t1w"]) == [fine.name]
