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
import sys
from pathlib import Path

import pytest
import rdflib
from rdflib import RDF

from src.nidm_converter.nidm_merge import (
    RDFS_TYPE,
    IQMLinkError,
    check_iqm_records,
    fix_csv2nidm_types,
    merge_iqms_into_nidm,
)
from src.run import main, process_subject
from tests.nidm_fixtures import UCLA_IMAGES, input_nidm_ttl, iqm_nidm_ttl

PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")
NIDM = rdflib.Namespace("http://purl.org/nidash/nidm#")
DCT = rdflib.Namespace("http://purl.org/dc/terms/")
NIIRI = rdflib.Namespace("http://iri.nidash.org/")
NDAR = rdflib.Namespace("https://ndar.nih.gov/api/datadictionary/v2/dataelement/")
SIO = rdflib.Namespace("http://semanticscience.org/ontology/sio.owl#")
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
        """The merge parses its input by extension, so a .jsonld path works.

        This covers the function only; the app refuses a non-Turtle input
        NIDM before merging (test_jsonld_input_nidm_fails_without_writing_nidm).
        """
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

    def test_link_error_names_the_input_and_the_remedy(self, tmp_path, logger):
        """The error points at the input NIDM as found, not the working copy"""
        jsons = ["/work/sub-51209_ses-1_run-2_T1w.json"]
        copy = _write(tmp_path / "out" / "nidm.ttl", input_nidm_ttl())
        found = tmp_path / "NIDM" / "sub-51209" / "ses-1" / "nidm.ttl"
        iqm = _write(tmp_path / "iqm.ttl", iqm_nidm_ttl(jsons))

        with pytest.raises(IQMLinkError) as err:
            merge_iqms_into_nidm(copy, iqm, copy, logger, source=found)
        message = str(err.value)
        assert str(found) in message
        assert "bidsmri2nidm" in message
        assert message.isascii()

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


class TestFixCsv2nidmTypes:
    """csv2nidm's rdfs:type triples become rdf:type (#26)."""

    CSV2NIDM_SHAPE = """\
@prefix nidm: <http://purl.org/nidash/nidm#> .
@prefix niiri: <http://iri.nidash.org/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
niiri:agent a prov:Agent ; rdfs:type nidm:SoftwareAgent .
niiri:record a prov:Entity ; rdfs:type nidm:DerivativeCollection .
"""

    def test_rdfs_type_becomes_rdf_type(self, tmp_path):
        ttl = _write(tmp_path / "iqms.ttl", self.CSV2NIDM_SHAPE)
        fix_csv2nidm_types(ttl)

        g = rdflib.Graph()
        g.parse(ttl, format="turtle")
        assert not list(g.triples((None, RDFS_TYPE, None)))
        assert set(g.objects(NIIRI.agent, RDF.type)) == {
            PROV.Agent, NIDM.SoftwareAgent, PROV.SoftwareAgent,
        }
        assert set(g.objects(NIIRI.record, RDF.type)) == {
            PROV.Entity, NIDM.DerivativeCollection,
        }

    def test_agent_typed_only_nidm_software_agent_gets_prov(self, tmp_path):
        """The csv2nidm -nidm shape: rdf:type, but no prov:SoftwareAgent"""
        ttl = _write(tmp_path / "iqms.ttl", self.CSV2NIDM_SHAPE.replace(
            "rdfs:type", "a"))

        assert fix_csv2nidm_types(ttl) == 1
        g = rdflib.Graph()
        g.parse(ttl, format="turtle")
        assert (NIIRI.agent, RDF.type, PROV.SoftwareAgent) in g

    def test_correct_graph_is_not_rewritten(self, tmp_path):
        """Output shaped like PyNIDM#457's csv2nidm is left byte for byte"""
        # A layout rdflib would not write, so a rewrite would show.
        text = (
            "@prefix nidm: <http://purl.org/nidash/nidm#> .\n"
            "@prefix niiri: <http://iri.nidash.org/> .\n"
            "@prefix prov: <http://www.w3.org/ns/prov#> .\n"
            "niiri:agent a nidm:SoftwareAgent, prov:Agent, prov:SoftwareAgent .\n"
            "niiri:record a nidm:DerivativeCollection, prov:Entity .\n"
        )
        ttl = _write(tmp_path / "iqms.ttl", text)
        mtime = ttl.stat().st_mtime_ns

        assert fix_csv2nidm_types(ttl) == 0
        assert ttl.read_text() == text
        assert ttl.stat().st_mtime_ns == mtime


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


def _subject_nodes(ttl: Path):
    """Nodes that say they are a subject or a project, by any typing.

    csv2nidm mints a Person per CSV row (carrying ndar:src_subject_id) and a
    Project, which the merge removes by their rdf:type. Counting the
    properties as well as the types means a renamed type in a later PyNIDM,
    which the merge would miss, still shows up here as a second subject.
    """
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")

    def typed(cls):
        return {n for p in (RDF.type, RDFS_TYPE) for n in g.subjects(p, cls)}

    return {
        "persons": typed(PROV.Person),
        "subject_ids": set(g.subjects(NDAR.src_subject_id, None)),
        "subject_agents": {
            g.value(assoc, PROV.agent)
            for assoc in g.subjects(PROV.hadRole, SIO.Subject)
        },
        "projects": typed(NIDM.Project),
    }


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
    # One subject and one project: the input's, not csv2nidm's per-row copies.
    assert _subject_nodes(ttl) == {
        "persons": {NIIRI.person},
        "subject_ids": {NIIRI.person},
        "subject_agents": {NIIRI.person},
        "projects": {NIIRI.project},
    }


@needs_csv2nidm
def test_input_nidm_without_the_image_fails_the_subject(tmp_path, logger, caplog):
    """An IQM set that cannot be linked fails the job instead of vanishing"""
    nidm_dir = tmp_path / "nidm"
    found = _write(nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
    stems = SES1_STEMS + ["sub-51209_ses-1_run-2_T1w"]
    with caplog.at_level(logging.ERROR):
        ok, _ = _run(tmp_path, stems, nidm_dir, logger)

    assert ok is False
    # The input that has to be fixed, not the copy in the output directory.
    assert str(found) in caplog.text


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


# Session runs carry only their own session's IQMs.
def _bids_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        '{"Name": "test", "BIDSVersion": "1.8.0"}'
    )
    for ses in ("1", "2"):
        (root / "sub-51209" / f"ses-{ses}" / "anat").mkdir(parents=True, exist_ok=True)
    return root


@needs_csv2nidm
def test_session_run_takes_only_its_session_from_a_shared_mriqc_tree(
    tmp_path, monkeypatch
):
    """--mriqc-output-dir with two sessions: ses-1's nidm.ttl holds ses-1 only"""
    ses2_stems = [s.replace("ses-1", "ses-2") for s in SES1_STEMS]
    mriqc_root = _mriqc_tree(tmp_path / "existing", SES1_STEMS + ses2_stems)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "run.py", str(_bids_dir(tmp_path / "bids")), str(out), "participant",
        "--participant-label", "51209", "--session-label", "1",
        "--mriqc-output-dir", str(mriqc_root),
        "--nidm-input-dir", str(tmp_path / "no_nidm"),
    ])

    assert main() == 0
    links = _linked_images(out / "sub-51209" / "ses-1" / "nidm.ttl")
    assert sorted(links) == sorted(f"{s}.json" for s in SES1_STEMS)


def _process_session(tmp_path, stems, session_id, logger, nidm_input_dir=None):
    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / f"ses-{session_id}"
    mriqc_dir = _mriqc_tree(tmp_path / "existing", stems)
    return process_subject(
        subject_id="51209", bids_dir=tmp_path / "bids", output_dir=output_dir,
        subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id=session_id,
        nidm_input_dir=nidm_input_dir or tmp_path / "no_nidm", skip_mriqc=True,
        skip_nidm=True, logger=logger,
    ), subject_dir


def test_session_run_skips_iqms_without_a_session(tmp_path, logger, caplog):
    """An IQM JSON with no ses entity cannot belong to the session and is logged"""
    stems = ["sub-51209_ses-1_run-1_T1w"]
    no_ses = tmp_path / "existing" / "mriqc" / "sub-51209" / "anat" / "sub-51209_T1w.json"
    no_ses.parent.mkdir(parents=True, exist_ok=True)
    no_ses.write_text(json.dumps(T1W_IQMS))
    with caplog.at_level(logging.INFO):
        ok, _ = _process_session(tmp_path, stems, "1", logger)

    assert ok is True
    assert "sub-51209_T1w.json" in caplog.text
    assert "Found 1 MRIQC JSON file(s)" in caplog.text


def test_session_run_without_iqms_for_its_session_fails(tmp_path, logger, caplog):
    """IQMs for other sessions only: the session's job fails, naming it"""
    with caplog.at_level(logging.ERROR):
        ok, _ = _process_session(tmp_path, SES1_STEMS, "3", logger)

    assert ok is False
    assert "ses-3" in caplog.text


def test_jsonld_input_nidm_fails_without_writing_nidm(tmp_path, logger, caplog):
    """A JSON-LD input NIDM is refused by name, not misread as Turtle"""
    g = rdflib.Graph()
    g.parse(data=input_nidm_ttl(), format="turtle")
    found = tmp_path / "nidm" / "sub-51209" / "sub-51209.jsonld"
    found.parent.mkdir(parents=True)
    g.serialize(destination=str(found), format="json-ld")
    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    mriqc_dir = _mriqc_tree(tmp_path / "existing", SES1_STEMS)
    with caplog.at_level(logging.ERROR):
        ok = process_subject(
            subject_id="51209", bids_dir=tmp_path / "bids", output_dir=output_dir,
            subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
            nidm_input_dir=tmp_path / "nidm", skip_mriqc=True, skip_nidm=False,
            logger=logger,
        )

    assert ok is False
    assert str(found) in caplog.text
    assert not (subject_dir / "nidm.ttl").exists()


# PyNIDM's own query API must find the IQM records (#26).
@needs_csv2nidm
@pytest.mark.parametrize("with_input", [False, True], ids=["no_input", "input_nidm"])
def test_pynidm_derivative_query_finds_every_iqm_record(
    tmp_path, logger, monkeypatch, with_input
):
    """GetDerivativesDataForSubject returns one collection per IQM JSON.

    The query only follows derivative activities associated with an agent
    that has rdf:type prov:SoftwareAgent. csv2nidm (PyNIDM 4.5.0) types the
    MRIQC agent with rdfs:type nidm:SoftwareAgent instead, which the query
    never sees, so it found no MRIQC data at all.
    """
    # PyNIDM 5 moved the query layer to nidm.linkml.experiment (lowercase
    # modules); 4.x has it under nidm.experiment.
    try:
        from nidm.linkml.experiment import cde
        from nidm.linkml.experiment import query
    except ImportError:
        from nidm.experiment import CDE as cde
        from nidm.experiment import Query as query

    # IQM data elements are defined in the graph itself; the CDE fallback
    # would download the ANTs/FreeSurfer/FSL vocabularies.
    monkeypatch.setattr(cde, "getCDEs", lambda *a, **k: rdflib.Graph())

    nidm_dir = tmp_path / "nidm"
    if with_input:
        _write(nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
    ok, ttl = _run(tmp_path, SES1_STEMS, nidm_dir, logger)
    assert ok is True

    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    subjects = {
        g.value(assoc, PROV.agent)
        for assoc in g.subjects(PROV.hadRole, SIO.Subject)
        if (None, PROV.qualifiedAssociation, assoc) in g
    }
    collections = {}
    for subject in subjects:
        collections.update(query.GetDerivativesDataForSubject((g,), None, subject))

    assert len(collections) == len(SES1_STEMS)
    for collection in collections.values():
        assert collection["StatCollectionType"] == "DerivativeCollection"
        assert collection["values"]
