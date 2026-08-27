"""Regression tests for the per-subject output layout.

The layout is the contract between this app and BABS: `zip_foldernames:
{${subid}: ...}` makes <output_dir>/sub-<id> the zip's top-level folder, so
anything written outside that directory never ships, and anything written
inside it ships in every subject's zip. These tests pin both halves.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.nidm_converter.nidm_utils import (
    NIDM_FILENAME,
    build_nidm_filename,
    build_subject_output_path,
)
from src.run import _cleanup_nidm_intermediates, process_subject
from src.utils import create_dataset_description


def _make_mriqc_json(path: Path, subject_id: str, session_id=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"subject_id": subject_id}
    if session_id:
        meta["session_id"] = session_id
    path.write_text(json.dumps({"cjv": 0.4, "bids_meta": meta}))


class TestSubjectOutputPath:
    def test_no_app_name_wrapper(self, tmp_path):
        """The old <out>/mriqc-nidm_bidsapp/nidm/ wrapper must not come back."""
        result = build_subject_output_path(tmp_path, "0051456")
        assert result == tmp_path / "sub-0051456"
        assert "mriqc-nidm_bidsapp" not in str(result)
        assert "nidm" not in result.parts

    def test_session_nests_under_subject(self, tmp_path):
        assert build_subject_output_path(tmp_path, "01", "baseline") == (
            tmp_path / "sub-01" / "ses-baseline"
        )

    def test_labels_normalized(self, tmp_path):
        assert build_subject_output_path(tmp_path, "sub-01", "ses-x") == (
            tmp_path / "sub-01" / "ses-x"
        )

    @pytest.mark.parametrize(
        "args", [("01",), ("01", "baseline"), ("0051456", None)]
    )
    def test_filename_is_always_nidm_ttl(self, args):
        """Subject identity lives in the directory, never in the filename."""
        assert build_nidm_filename(*args) == "nidm.ttl"
        assert NIDM_FILENAME == "nidm.ttl"


class TestIntermediateCleanup:
    def test_removes_bak_and_json_sidecars(self, tmp_path, caplog):
        """csv2nidm's scratch files must not ship inside the subject zip."""
        import logging

        subject_dir = tmp_path / "sub-01"
        subject_dir.mkdir()
        (subject_dir / "nidm.ttl").write_text("@prefix x: <http://x> .")
        (subject_dir / "nidm.ttl.bak").write_text("stale")
        (subject_dir / "nidm.ttl.json").write_text("{}")

        _cleanup_nidm_intermediates(subject_dir, logging.getLogger("t"))

        assert (subject_dir / "nidm.ttl").exists()
        assert not (subject_dir / "nidm.ttl.bak").exists()
        assert not (subject_dir / "nidm.ttl.json").exists()


class TestDatasetDescriptionPlacement:
    def test_written_at_derivative_root_not_in_subject_dir(self, tmp_path):
        """A copy inside sub-<id>/ would be duplicated into every subject zip."""
        desc = create_dataset_description(tmp_path, version="0.1.0")

        assert desc == tmp_path / "dataset_description.json"
        assert desc.exists()
        assert not list(tmp_path.glob("sub-*"))
        assert not (tmp_path / "mriqc-nidm_bidsapp").exists()


class TestProcessSubjectLayout:
    def test_writes_nidm_ttl_into_subject_dir_and_keeps_csvs_out(self, tmp_path):
        """CSV intermediates stage outside subject_dir; nidm.ttl lands inside."""
        import logging

        output_dir = tmp_path / "out"
        subject_dir = output_dir / "sub-01"
        mriqc_dir = subject_dir / "mriqc"
        _make_mriqc_json(mriqc_dir / "sub-01" / "anat" / "sub-01_T1w.json", "01")

        captured = {}

        def fake_json2csv(json_file, csv_file, logger):
            captured["csv_file"] = Path(csv_file)
            Path(csv_file).parent.mkdir(parents=True, exist_ok=True)
            Path(csv_file).write_text("a,b\n1,2\n")
            soft = Path(csv_file).with_name("software.csv")
            soft.write_text("x\n")
            return Path(csv_file), soft

        def fake_csv2nidm(**kwargs):
            out = Path(kwargs["output_ttl"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("@prefix x: <http://x> .")
            # csv2nidm leaves these behind next to its target
            out.with_suffix(".ttl.bak").write_text("stale")
            return True

        with patch("src.run.convert_mriqc_json_to_csv", side_effect=fake_json2csv), \
             patch("src.run.convert_csv_to_nidm", side_effect=fake_csv2nidm), \
             patch("src.run.get_mriqc_dictionary", return_value=tmp_path / "d.csv"):
            ok = process_subject(
                subject_id="01",
                bids_dir=tmp_path / "bids",
                output_dir=output_dir,
                subject_dir=subject_dir,
                mriqc_dir=mriqc_dir,
                session_id=None,
                nidm_input_dir=None,
                skip_mriqc=True,
                skip_nidm=False,
                logger=logging.getLogger("t"),
            )

        assert ok is True
        assert (subject_dir / "nidm.ttl").exists()
        # The CSV must have been staged outside the directory BABS zips.
        assert subject_dir not in captured["csv_file"].parents
        assert not list(subject_dir.glob("*.csv"))
        # And the scratch files csv2nidm dropped are gone.
        assert not list(subject_dir.glob("*.bak"))
