"""Tests for attaching MRIQC IQM records to an input NIDM graph.

csv2nidm's own append mode (-nidm) links a derivative to an acquisition by
session/task/run. bidsmri2nidm records run and task only on functional
images, so csv2nidm drops T1w IQM rows without a run and links T1w rows
that have one to the BOLD acquisition with the same run number. The app
therefore lets csv2nidm write the IQM records on their own and links each
one to its image by filename.
"""

import json
import logging
import shutil
from pathlib import Path

import pytest
import rdflib
from rdflib import RDF

from src.nidm_converter.nidm_merge import (
    RDFS_TYPE,
    IQMLinkError,
    check_iqm_records,
    merge_iqms_into_nidm,
)
from src.run import process_subject
from tests.nidm_fixtures import UCLA_IMAGES, input_nidm_ttl, iqm_nidm_ttl

PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")
NIDM = rdflib.Namespace("http://purl.org/nidash/nidm#")
DCT = rdflib.Namespace("http://purl.org/dc/terms/")
NIIRI = rdflib.Namespace("http://iri.nidash.org/")
NFO_FILENAME = rdflib.URIRef(
    "http://www.semanticdesktop.org/ontologies/2007/03/22/nfo#filename"
)


@pytest.fixture
def logger():
    return logging.getLogger("test_nidm_merge")


def _linked_images(ttl: Path):
    """Map each IQM JSON basename to the image filename(s) its activity used."""
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    links = {}
    for ent, loc in g.subject_objects(PROV.Location):
        if not str(loc).endswith(".json"):
            continue
        images = []
        for act in g.objects(ent, PROV.wasGeneratedBy):
            for acq_act in g.objects(act, PROV.used):
                for obj in g.subjects(PROV.wasGeneratedBy, acq_act):
                    for fn in g.objects(obj, NFO_FILENAME):
                        images.append(str(fn).rsplit("/", 1)[-1])
        links[str(loc).rsplit("/", 1)[-1]] = sorted(images)
    return links


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestMergeIqmsIntoNidm:
    def test_links_each_iqm_record_to_its_own_image(self, tmp_path, logger):
        stems = [stem for _, stem in UCLA_IMAGES]
        jsons = [f"/work/mriqc/{stem}.json" for stem in stems]
        base = _write(tmp_path / "in.ttl", input_nidm_ttl())
        iqm = _write(tmp_path / "iqm.ttl", iqm_nidm_ttl(jsons))
        out = tmp_path / "out.ttl"

        n = merge_iqms_into_nidm(base, iqm, out, logger)

        assert n == len(stems)
        links = _linked_images(out)
        for stem in stems:
            assert links[f"{stem}.json"] == [f"{stem}.nii.gz"]

    def test_reuses_input_subject_and_project(self, tmp_path, logger):
        """No second Person or Project is introduced for the subject"""
        jsons = ["/work/sub-51209_ses-1_run-1_T1w.json"]
        base = _write(tmp_path / "in.ttl", input_nidm_ttl())
        iqm = _write(tmp_path / "iqm.ttl", iqm_nidm_ttl(jsons))
        out = tmp_path / "out.ttl"

        merge_iqms_into_nidm(base, iqm, out, logger)

        g = rdflib.Graph()
        g.parse(out, format="turtle")
        assert set(g.subjects(RDF.type, PROV.Person)) == {NIIRI.person}
        assert set(g.subjects(RDF.type, NIDM.Project)) == {NIIRI.project}
        assert not set(g.subjects(RDF.type, PROV.Collection))
        der_act = NIIRI["der-act-0"]
        assert (der_act, DCT.isPartOf, NIIRI.project) in g
        agents = {
            g.value(assoc, PROV.agent)
            for assoc in g.objects(der_act, PROV.qualifiedAssociation)
        }
        assert NIIRI.person in agents
        # The export record now refers to the input project
        assert (NIIRI.export, PROV.used, NIIRI.project) in g
        # Nothing still points at a node that was dropped
        dropped = {NIIRI["iqm-project"], NIIRI["iqm-collection"],
                   NIIRI["iqm-person-0"]}
        assert not dropped & set(g.objects())
        assert not dropped & set(g.subjects())

    def test_keeps_input_graph_and_iqm_values(self, tmp_path, logger):
        jsons = ["/work/sub-51209_ses-2_run-1_T1w.json"]
        base = _write(tmp_path / "in.ttl", input_nidm_ttl())
        iqm = _write(tmp_path / "iqm.ttl", iqm_nidm_ttl(jsons))
        out = tmp_path / "out.ttl"

        merge_iqms_into_nidm(base, iqm, out, logger)

        g_in = rdflib.Graph()
        g_in.parse(base, format="turtle")
        g = rdflib.Graph()
        g.parse(out, format="turtle")
        assert len(g_in) > 0
        assert all(t in g for t in g_in if not isinstance(t[2], rdflib.BNode)
                   and not isinstance(t[0], rdflib.BNode))
        ent = NIIRI["der-ent-0"]
        assert (ent, RDFS_TYPE, NIDM.DerivativeCollection) in g
        cjv = rdflib.URIRef("https://mriqc.readthedocs.io/en/stable/cjv_x")
        assert float(g.value(ent, cjv)) == pytest.approx(0.1)

    def test_jsonld_input(self, tmp_path, logger):
        """A JSON-LD input NIDM is read as JSON-LD"""
        g = rdflib.Graph()
        g.parse(data=input_nidm_ttl(), format="turtle")
        base = tmp_path / "in.jsonld"
        g.serialize(destination=str(base), format="json-ld")
        jsons = ["/work/sub-51209_ses-1_run-1_T1w.json"]
        iqm = _write(tmp_path / "iqm.ttl", iqm_nidm_ttl(jsons))
        out = tmp_path / "out.ttl"

        assert merge_iqms_into_nidm(base, iqm, out, logger) == 1
        assert _linked_images(out) == {
            "sub-51209_ses-1_run-1_T1w.json": ["sub-51209_ses-1_run-1_T1w.nii.gz"]
        }

    def test_image_missing_from_input_fails(self, tmp_path, logger):
        """An IQM record with no acquisition in the input is an error"""
        jsons = ["/work/sub-51209_ses-1_run-2_T1w.json"]
        base = _write(tmp_path / "in.ttl", input_nidm_ttl())
        iqm = _write(tmp_path / "iqm.ttl", iqm_nidm_ttl(jsons))

        with pytest.raises(IQMLinkError, match="sub-51209_ses-1_run-2_T1w"):
            merge_iqms_into_nidm(base, iqm, tmp_path / "out.ttl", logger)
        assert not (tmp_path / "out.ttl").exists()

    def test_ambiguous_image_fails(self, tmp_path, logger):
        """Two acquisitions with the same image name cannot be told apart"""
        images = UCLA_IMAGES + [("2", "sub-51209_ses-1_run-1_T1w")]
        jsons = ["/work/sub-51209_ses-1_run-1_T1w.json"]
        base = _write(tmp_path / "in.ttl", input_nidm_ttl(images=images))
        iqm = _write(tmp_path / "iqm.ttl", iqm_nidm_ttl(jsons))

        with pytest.raises(IQMLinkError, match="2 acquisitions"):
            merge_iqms_into_nidm(base, iqm, tmp_path / "out.ttl", logger)


class TestCheckIqmRecords:
    def test_one_record_per_json_passes(self, tmp_path):
        jsons = [Path("/w/a_T1w.json"), Path("/w/b_bold.json")]
        ttl = _write(tmp_path / "n.ttl", iqm_nidm_ttl([str(p) for p in jsons]))
        assert check_iqm_records(ttl, jsons) == []

    def test_missing_record_is_reported(self, tmp_path):
        jsons = [Path("/w/a_T1w.json"), Path("/w/b_bold.json")]
        ttl = _write(tmp_path / "n.ttl", iqm_nidm_ttl([str(jsons[0])]))
        problems = check_iqm_records(ttl, jsons)
        assert len(problems) == 1
        assert "b_bold.json" in problems[0]

    def test_duplicate_record_is_reported(self, tmp_path):
        jsons = [Path("/w/a_T1w.json")]
        ttl = _write(tmp_path / "n.ttl", iqm_nidm_ttl([str(jsons[0])] * 2))
        problems = check_iqm_records(ttl, jsons)
        assert len(problems) == 1
        assert "2 records" in problems[0]

    def test_records_from_other_runs_are_ignored(self, tmp_path):
        """IQM records already in the input NIDM do not count"""
        jsons = [Path("/w/a_T1w.json")]
        ttl = _write(
            tmp_path / "n.ttl", iqm_nidm_ttl([str(jsons[0]), "/old/a_T1w.json"])
        )
        assert check_iqm_records(ttl, jsons) == []


# End to end through process_subject with the real csv2nidm.
needs_csv2nidm = pytest.mark.skipif(
    shutil.which("csv2nidm") is None, reason="csv2nidm (PyNIDM) not installed"
)

T1W_IQMS = {
    "cjv": 0.4, "cnr": 3.1, "efc": 0.6, "fber": 3000.0, "snr_total": 9.0,
}
BOLD_IQMS = {"aor": 0.001, "fd_mean": 0.12, "gsr_x": 0.01, "tsnr": 40.0}


def _mriqc_tree(subject_dir: Path, stems):
    """MRIQC outputs under <subject_dir>/mriqc for one subject/session."""
    mriqc_dir = subject_dir / "mriqc"
    for stem in stems:
        bold = stem.endswith("_bold")
        ses = stem.split("_ses-")[1].split("_")[0]
        path = (mriqc_dir / "sub-51209" / f"ses-{ses}"
                / ("func" if bold else "anat") / f"{stem}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(BOLD_IQMS if bold else T1W_IQMS)
        data["bids_meta"] = {"subject": "51209", "session": ses,
                             "datatype": "func" if bold else "anat"}
        data["provenance"] = {"software": "mriqc", "version": "25.0.0"}
        path.write_text(json.dumps(data))
    return mriqc_dir


def _run(tmp_path, stems, nidm_input_dir, logger):
    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    mriqc_dir = _mriqc_tree(subject_dir, stems)
    bids = tmp_path / "bids"
    bids.mkdir(exist_ok=True)
    ok = process_subject(
        subject_id="51209", bids_dir=bids, output_dir=output_dir,
        subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
        nidm_input_dir=nidm_input_dir, skip_mriqc=True, skip_nidm=False,
        logger=logger,
    )
    return ok, subject_dir / "nidm.ttl"


SES1_STEMS = [
    "sub-51209_ses-1_acq-hires_run-1_T1w",
    "sub-51209_ses-1_run-1_T1w",
    "sub-51209_ses-1_task-rest_run-1_bold",
]


@needs_csv2nidm
def test_no_input_nidm_keeps_every_iqm_record(tmp_path, logger):
    """Every IQM JSON of the job becomes a record, not only the first"""
    stems = SES1_STEMS + ["sub-51209_ses-1_run-2_T1w"]
    ok, ttl = _run(tmp_path, stems, tmp_path / "no_nidm", logger)

    assert ok is True
    assert sorted(_linked_images(ttl)) == sorted(f"{s}.json" for s in stems)


@needs_csv2nidm
def test_input_nidm_links_t1w_to_its_own_acquisition(tmp_path, logger):
    """UCLA_Long layout: per-session input, T1w never linked to BOLD"""
    nidm_dir = tmp_path / "nidm"
    _write(nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
    ok, ttl = _run(tmp_path, SES1_STEMS, nidm_dir, logger)

    assert ok is True
    links = _linked_images(ttl)
    assert {k: v for k, v in links.items() if k in
            {f"{s}.json" for s in SES1_STEMS}} == {
        f"{s}.json": [f"{s}.nii.gz"] for s in SES1_STEMS
    }


@needs_csv2nidm
def test_input_nidm_without_the_image_fails_the_subject(tmp_path, logger):
    """An IQM set that cannot be linked fails the job instead of vanishing"""
    nidm_dir = tmp_path / "nidm"
    _write(nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
    stems = SES1_STEMS + ["sub-51209_ses-1_run-2_T1w"]
    ok, _ = _run(tmp_path, stems, nidm_dir, logger)

    assert ok is False


def test_dropped_iqm_record_fails_the_subject(tmp_path, logger):
    """If csv2nidm writes fewer records than IQM JSONs, the job fails"""
    from unittest.mock import patch

    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    stems = ["sub-51209_ses-1_run-1_T1w", "sub-51209_ses-1_acq-hires_run-1_T1w"]
    mriqc_dir = _mriqc_tree(subject_dir, stems)
    kept = sorted(mriqc_dir.rglob("*.json"))[0]

    def csv2nidm_dropping_a_row(**kwargs):
        Path(kwargs["output_ttl"]).write_text(iqm_nidm_ttl([str(kept)]))
        return True

    with patch("src.run.convert_csv_to_nidm", side_effect=csv2nidm_dropping_a_row):
        ok = process_subject(
            subject_id="51209", bids_dir=tmp_path, output_dir=output_dir,
            subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
            nidm_input_dir=tmp_path / "no_nidm", skip_mriqc=True,
            skip_nidm=False, logger=logger,
        )
    assert ok is False
