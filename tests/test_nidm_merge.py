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
import os
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

    def test_iqm_properties_keep_the_mriqc_prefix(self, tmp_path, logger):
        # csv2nidm 5.0.0 binds no prefix name to the MRIQC namespace, so the
        # IQM properties came out as ns1:cjv_x instead of mriqc:cjv_x. Same
        # IRIs, but the files are harder to read and differ from earlier
        # releases. The merged output names the namespace mriqc again.
        jsons = ["/work/sub-51209_ses-2_run-1_T1w.json"]
        # Neither bidsmri2nidm's input nor csv2nidm 5's output names it.
        no_prefix = "@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> .\n"
        base_text = input_nidm_ttl().replace(no_prefix, "")
        iqm_text = iqm_nidm_ttl(jsons).replace(no_prefix, "").replace(
            "mriqc:cjv_x", "<https://mriqc.readthedocs.io/en/stable/cjv_x>")
        assert "mriqc:" not in base_text + iqm_text
        base = _write(tmp_path / "in.ttl", base_text)
        iqm = _write(tmp_path / "iqm.ttl", iqm_text)
        out = tmp_path / "out.ttl"

        merge_iqms_into_nidm(base, iqm, out, logger)

        text = out.read_text()
        assert "@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> ." in text
        assert "mriqc:cjv_x" in text
        assert "ns1:" not in text

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


def _assert_clean_mriqc_output(ttl: Path, caplog):
    """The IQM properties are under the mriqc prefix, and a clean run logs no
    warning (csv2nidm's SciCrunch notice included)."""
    text = ttl.read_text()
    assert "@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> ." in text
    assert "mriqc:cjv" in text
    assert "ns1:" not in text
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


@needs_csv2nidm
def test_no_input_nidm_keeps_every_iqm_record(tmp_path, logger, caplog, monkeypatch):
    """Every IQM JSON of the job becomes a record, not only the first"""
    # csv2nidm 5.0.0 names the MRIQC namespace ns1 under this seed; the child
    # inherits it through subprocess.run's environment.
    monkeypatch.setenv("PYTHONHASHSEED", "1")
    stems = SES1_STEMS + ["sub-51209_ses-1_run-2_T1w"]
    with caplog.at_level(logging.DEBUG):
        ok, ttl = _run(tmp_path, stems, tmp_path / "no_nidm", logger)

    assert ok is True
    assert sorted(_linked_images(ttl)) == sorted(f"{s}.json" for s in stems)
    _assert_clean_mriqc_output(ttl, caplog)


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
def test_input_nidm_links_t1w_to_its_own_acquisition(tmp_path, logger, caplog, monkeypatch):
    """UCLA_Long layout: per-session input, T1w never linked to BOLD"""
    monkeypatch.setenv("PYTHONHASHSEED", "1")
    nidm_dir = tmp_path / "nidm"
    found = _write(nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
    with caplog.at_level(logging.DEBUG):
        ok, ttl = _run(tmp_path, SES1_STEMS, nidm_dir, logger)

    assert ok is True
    _assert_clean_mriqc_output(ttl, caplog)
    assert found.read_text() == input_nidm_ttl()
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
    # No copy of the input is left looking like a finished output.
    subject_dir = tmp_path / "out" / "sub-51209" / "ses-1"
    assert not (subject_dir / "nidm.ttl").exists()
    assert [p.name for p in subject_dir.iterdir() if p.is_file()] == []
    assert found.read_text() == input_nidm_ttl()


@needs_csv2nidm
def test_failed_csv2nidm_logs_its_cause_first(tmp_path, logger, caplog, monkeypatch):
    """An IQM without a row in the data dictionary makes the real csv2nidm ask
    on stdin and fail (EOF under a batch job). The first error logged names
    that cause, not the SciCrunch API key notice csv2nidm prints on every run."""
    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    mriqc_dir = _mriqc_tree(subject_dir, ["sub-51209_ses-1_run-1_T1w"])
    json_file = next(mriqc_dir.rglob("*.json"))
    data = json.loads(json_file.read_text())
    data["zzz_not_in_the_dictionary"] = 1.5
    json_file.write_text(json.dumps(data))
    with caplog.at_level(logging.INFO):
        ok = process_subject(
            subject_id="51209", bids_dir=tmp_path, output_dir=output_dir,
            subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
            nidm_input_dir=tmp_path / "no_nidm", skip_mriqc=True,
            skip_nidm=False, logger=logger,
        )
    assert ok is False
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, caplog.text
    assert "EOFError" in errors[0].splitlines()[0], errors[0]
    assert not any("SciCrunch" in m for m in errors), errors
    assert not any("SciCrunch" in r.getMessage() for r in caplog.records
                   if r.levelno >= logging.WARNING)
    assert not (subject_dir / "nidm.ttl").exists()


UNMAPPED_IQM_RUN = """
import json, logging, sys
from pathlib import Path
from src.run import process_subject
from tests.test_nidm_merge import _mriqc_tree

logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
work = Path(sys.argv[1])
subject_dir = work / "out" / "sub-51209" / "ses-1"
mriqc_dir = _mriqc_tree(subject_dir, ["sub-51209_ses-1_run-1_T1w"])
json_file = next(mriqc_dir.rglob("*.json"))
data = json.loads(json_file.read_text())
data["zzz_not_in_the_dictionary"] = 1.5
json_file.write_text(json.dumps(data))
ok = process_subject(
    subject_id="51209", bids_dir=work, output_dir=work / "out",
    subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
    nidm_input_dir=work / "no_nidm", skip_mriqc=True, skip_nidm=False,
    logger=logging.getLogger("unmapped"))
sys.exit(0 if ok else 1)
"""


@needs_csv2nidm
def test_csv2nidm_never_reads_the_apps_stdin(tmp_path):
    """csv2nidm asks on stdin for an IQM missing from the data dictionary. It
    used to inherit the app's stdin, so from a terminal (here: a pipe nobody
    writes to or closes) it waited until the 300 s timeout. It must fail at
    once with the EOFError, whatever the app's stdin is."""
    import os
    import signal
    import subprocess

    root = Path(__file__).resolve().parent.parent
    log = tmp_path / "child.log"
    with open(log, "w") as out:
        child = subprocess.Popen(
            [sys.executable, "-c", UNMAPPED_IQM_RUN, str(tmp_path)],
            cwd=root, stdin=subprocess.PIPE, stdout=out, stderr=out,
            start_new_session=True)
    try:
        child.wait(timeout=120)
    except subprocess.TimeoutExpired:
        pass
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            pytest.fail("csv2nidm waited on the app's stdin: " + log.read_text()[-2000:])
        child.stdin.close()
    assert child.returncode == 1, log.read_text()[-3000:]
    errors = [line for line in log.read_text().splitlines() if line.startswith("ERROR")]
    assert errors and "EOFError" in errors[0], log.read_text()[-3000:]


def test_csv2nidm_is_started_with_stdin_at_eof(tmp_path):
    from src.nidm_converter.csv_to_nidm import convert_csv_to_nidm

    for name in ("iqms.csv", "dictionary.csv", "software.csv"):
        (tmp_path / name).write_text("x\n")
    import subprocess
    from unittest.mock import patch

    done = subprocess.CompletedProcess(
        args=["csv2nidm"], returncode=0, stdout="", stderr="")
    with patch("shutil.which", return_value="/usr/bin/csv2nidm"), \
            patch("subprocess.run", return_value=done) as run:
        convert_csv_to_nidm(
            csv_file=tmp_path / "iqms.csv", dictionary_csv=tmp_path / "dictionary.csv",
            software_metadata_csv=tmp_path / "software.csv", output_ttl=tmp_path / "o.ttl")
    assert run.call_args.kwargs.get("stdin") is subprocess.DEVNULL


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
    assert not (subject_dir / "nidm.ttl").exists()
    assert [p.name for p in subject_dir.iterdir() if p.is_file()] == []


def test_failed_csv2nidm_with_input_nidm_leaves_no_nidm_ttl(tmp_path, logger):
    """The input NIDM used to be copied to nidm.ttl before conversion, so a
    failed csv2nidm left an unmodified copy of the input as the output."""
    from unittest.mock import patch

    nidm_dir = tmp_path / "nidm"
    _write(nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
    with patch("src.run.convert_csv_to_nidm",
               side_effect=RuntimeError("csv2nidm failed: boom")):
        ok, ttl = _run(tmp_path, SES1_STEMS, nidm_dir, logger)
    assert ok is False
    assert not ttl.exists()
    assert [p.name for p in ttl.parent.iterdir() if p.is_file()] == []


@pytest.mark.parametrize("with_input", [False, True], ids=["no_input", "input_nidm"])
def test_successful_merge_replaces_nidm_ttl_and_leaves_no_temporary(tmp_path, logger, with_input):
    """The result, csv2nidm's graph or (with an input NIDM) the merged graph,
    is written to a temporary file beside nidm.ttl and renamed over the
    earlier run's nidm.ttl."""
    from unittest.mock import patch

    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    stems = ["sub-51209_ses-1_run-1_T1w"]
    mriqc_dir = _mriqc_tree(subject_dir, stems)
    jsons = sorted(mriqc_dir.rglob("*.json"))
    subject_dir.joinpath("nidm.ttl").write_text("stale output of an earlier run")
    nidm_input_dir = tmp_path / ("nidm" if with_input else "no_nidm")
    if with_input:
        _write(nidm_input_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())

    def csv2nidm(**kwargs):
        Path(kwargs["output_ttl"]).write_text(iqm_nidm_ttl([str(j) for j in jsons]))
        return True

    with patch("src.run.convert_csv_to_nidm", side_effect=csv2nidm):
        ok = process_subject(
            subject_id="51209", bids_dir=tmp_path, output_dir=output_dir,
            subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
            nidm_input_dir=nidm_input_dir, skip_mriqc=True,
            skip_nidm=False, logger=logger,
        )
    assert ok is True
    links = _linked_images(subject_dir / "nidm.ttl")
    assert sorted(links) == [f"{s}.json" for s in stems]
    # Merged: each record uses its acquisition from the input NIDM.
    assert links == {f"{s}.json": [f"{s}.nii.gz"] if with_input else [] for s in stems}
    assert [p.name for p in subject_dir.iterdir() if p.is_file()] == ["nidm.ttl"]


def _merge_with_stub_csv2nidm(tmp_path, logger, nidm_input_dir, output_dir=None):
    """process_subject on SES1_STEMS with an input NIDM, csv2nidm replaced by
    a stub writing a valid IQM graph; returns (ok, subject_dir)."""
    from unittest.mock import patch

    output_dir = output_dir or tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    mriqc_dir = _mriqc_tree(subject_dir, SES1_STEMS)
    jsons = sorted(mriqc_dir.rglob("*.json"))

    def csv2nidm(**kwargs):
        Path(kwargs["output_ttl"]).write_text(iqm_nidm_ttl([str(j) for j in jsons]))
        return True

    with patch("src.run.convert_csv_to_nidm", side_effect=csv2nidm):
        ok = process_subject(
            subject_id="51209", bids_dir=tmp_path, output_dir=output_dir,
            subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
            nidm_input_dir=nidm_input_dir, skip_mriqc=True, skip_nidm=False,
            logger=logger,
        )
    return ok, subject_dir


def _read_only_object(tmp_path, text):
    """A file shaped like a git-annex object: read-only, in a read-only directory."""
    obj = tmp_path / "annex" / "objects" / "SHA256E-s1--x.ttl"
    obj.parent.mkdir(parents=True)
    obj.write_text(text)
    obj.chmod(0o444)
    obj.parent.chmod(0o555)
    return obj


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_merge_leaves_the_input_nidm_unchanged(tmp_path, logger, kind):
    """The input NIDM is read, never written: its bytes, and for a symlink
    (a datalad dataset's annexed file) the link and its target, are the same
    after a successful merge."""
    nidm_dir = tmp_path / "nidm"
    found = nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl"
    found.parent.mkdir(parents=True)
    original = input_nidm_ttl()
    if kind == "symlink":
        target = _read_only_object(tmp_path, original)
        found.symlink_to(target)
    else:
        found.write_text(original)
    mtime = found.stat().st_mtime_ns
    try:
        ok, subject_dir = _merge_with_stub_csv2nidm(tmp_path, logger, nidm_dir)
        assert ok is True
        assert _linked_images(subject_dir / "nidm.ttl") == {
            f"{s}.json": [f"{s}.nii.gz"] for s in SES1_STEMS}
        assert found.read_text() == original
        assert found.stat().st_mtime_ns == mtime
        if kind == "symlink":
            assert found.is_symlink() and found.resolve() == target
    finally:
        if kind == "symlink":
            target.parent.chmod(0o755)


def test_input_nidm_in_the_output_directory_is_replaced_not_written(tmp_path, logger):
    """With the NIDM input directory set to the output directory, the input
    found is the subject's nidm.ttl itself. The new nidm.ttl replaces it by
    rename: an annexed input's link is replaced, its object is not written."""
    output_dir = tmp_path / "out"
    subject_nidm = output_dir / "sub-51209" / "ses-1" / "nidm.ttl"
    subject_nidm.parent.mkdir(parents=True)
    original = input_nidm_ttl()
    target = _read_only_object(tmp_path, original)
    subject_nidm.symlink_to(target)
    try:
        ok, subject_dir = _merge_with_stub_csv2nidm(
            tmp_path, logger, nidm_input_dir=output_dir, output_dir=output_dir)
        assert ok is True
        assert not subject_nidm.is_symlink()
        assert _linked_images(subject_nidm) == {
            f"{s}.json": [f"{s}.nii.gz"] for s in SES1_STEMS}
        assert target.read_text() == original
    finally:
        target.parent.chmod(0o755)


def test_successful_run_logs_the_nidm_it_wrote(tmp_path, logger, caplog):
    with caplog.at_level(logging.INFO):
        ok, subject_dir = _process_with_stub_csv2nidm(tmp_path, logger)
    assert ok is True
    assert f"Created consolidated NIDM: {subject_dir / 'nidm.ttl'}" in caplog.text


def test_rerun_that_converts_nothing_says_the_earlier_nidm_is_kept(tmp_path, logger, caplog):
    """When every IQM JSON of a re-run fails to convert, nothing is written and
    the earlier run's nidm.ttl stays. The log used to say "Created consolidated
    NIDM" for that file."""
    from unittest.mock import patch

    subject_dir = tmp_path / "out" / "sub-51209" / "ses-1"
    subject_dir.mkdir(parents=True)
    earlier = subject_dir / "nidm.ttl"
    earlier.write_text("output of an earlier run")
    with caplog.at_level(logging.INFO), patch(
            "src.run.convert_mriqc_json_to_csv", side_effect=ValueError("unreadable")):
        ok, _ = _process_with_stub_csv2nidm(tmp_path, logger)
    assert ok is False
    assert earlier.read_text() == "output of an earlier run"
    assert "Created consolidated NIDM" not in caplog.text
    assert f"No NIDM written for sub-51209; {earlier} from an earlier run is left as it was" \
        in caplog.text


def test_run_that_converts_nothing_says_no_nidm_was_written(tmp_path, logger, caplog):
    from unittest.mock import patch

    with caplog.at_level(logging.INFO), patch(
            "src.run.convert_mriqc_json_to_csv", side_effect=ValueError("unreadable")):
        ok, subject_dir = _process_with_stub_csv2nidm(tmp_path, logger)
    assert ok is False
    assert not (subject_dir / "nidm.ttl").exists()
    assert "Created consolidated NIDM" not in caplog.text
    assert "No NIDM written for sub-51209" in caplog.text


@needs_csv2nidm
def test_rerun_with_the_output_directory_as_nidm_input_fails(tmp_path, logger, caplog):
    """README: with the NIDM input directory set to the output directory, a
    re-run reads the first run's nidm.ttl, which already holds the IQM
    records, and fails the record check. The earlier nidm.ttl is kept. (A
    stub csv2nidm hides this: its record IRIs are the same on every run.)"""
    output_dir = tmp_path / "out"
    subject_nidm = _write(output_dir / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
    ok, _ = _run(tmp_path, SES1_STEMS, output_dir, logger)
    assert ok is True
    first = subject_nidm.read_bytes()
    with caplog.at_level(logging.ERROR):
        ok, _ = _run(tmp_path, SES1_STEMS, output_dir, logger)
    assert ok is False
    assert "does not hold one MRIQC record per IQM JSON" in caplog.text
    assert caplog.text.count("2 records in NIDM") == len(SES1_STEMS)
    assert subject_nidm.read_bytes() == first


@pytest.mark.parametrize("csv2nidm_version", ["4.x", "5.0.0"])
def test_no_input_nidm_output_names_the_mriqc_prefix(tmp_path, logger, csv2nidm_version):
    """Without an input NIDM, nidm.ttl is csv2nidm's own graph. csv2nidm 5.0.0
    names the MRIQC namespace ns1 or mriqc depending on the process's string
    hash seed (rdflib's Graph.__add__ binds prefixes from a set), and
    fix_csv2nidm_types does not rewrite its output, so the file came out
    with ns1: for some runs. Here csv2nidm writes ns1 every time."""
    from unittest.mock import patch

    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    stems = ["sub-51209_ses-1_run-1_T1w"]
    mriqc_dir = _mriqc_tree(subject_dir, stems)
    jsons = sorted(mriqc_dir.rglob("*.json"))
    text = iqm_nidm_ttl([str(j) for j in jsons]).replace(
        "@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> .",
        "@prefix ns1: <https://mriqc.readthedocs.io/en/stable/> .",
    ).replace("mriqc:cjv_x", "ns1:cjv_x")
    if csv2nidm_version == "5.0.0":
        # rdf:type and prov:SoftwareAgent already: fix_csv2nidm_types leaves
        # the file as csv2nidm wrote it.
        text = text.replace("rdfs:type", "a").replace(
            "nidm:SoftwareAgent, prov:Agent", "nidm:SoftwareAgent, prov:SoftwareAgent, prov:Agent")
    assert "mriqc:" not in text

    def csv2nidm(**kwargs):
        Path(kwargs["output_ttl"]).write_text(text)
        return True

    with patch("src.run.convert_csv_to_nidm", side_effect=csv2nidm):
        ok = process_subject(
            subject_id="51209", bids_dir=tmp_path, output_dir=output_dir,
            subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
            nidm_input_dir=tmp_path / "no_nidm", skip_mriqc=True,
            skip_nidm=False, logger=logger,
        )
    assert ok is True
    out = (subject_dir / "nidm.ttl").read_text()
    assert "@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> ." in out
    assert "mriqc:cjv_x" in out
    assert "ns1:" not in out


SEEDED_RUN = """
import logging, sys
from pathlib import Path
from tests.nidm_fixtures import input_nidm_ttl
from tests.test_nidm_merge import SES1_STEMS, _run, _write
work, with_input = Path(sys.argv[1]), sys.argv[2] == "1"
if with_input:
    _write(work / "nidm" / "sub-51209" / "ses-1" / "nidm.ttl", input_nidm_ttl())
ok, _ = _run(work, SES1_STEMS, work / "nidm", logging.getLogger("seeded"))
sys.exit(0 if ok else 1)
"""


@needs_csv2nidm
@pytest.mark.parametrize("with_input", [False, True], ids=["no_input", "input_nidm"])
def test_nidm_ttl_prefixes_do_not_depend_on_the_hash_seed(tmp_path, with_input):
    """rdflib binds prefixes from a set when graphs are combined, so the
    prefix a namespace gets in csv2nidm's output, and in the app's merge,
    depends on the string hash seed: http://purl.org/dc/dcmitype/ came out as
    dcmitype in one run and dctypes in the next. Seeds 0 and 1 gave the two
    names. The whole @prefix block must be the same for both, end to end
    with the real csv2nidm (the child's seed reaches csv2nidm too)."""
    import subprocess

    root = Path(__file__).resolve().parent.parent
    blocks = {}
    for seed in ("0", "1"):
        work = tmp_path / f"seed{seed}"
        work.mkdir()
        result = subprocess.run(
            [sys.executable, "-c", SEEDED_RUN, str(work), "1" if with_input else "0"],
            cwd=root, env=dict(os.environ, PYTHONHASHSEED=seed),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
        assert result.returncode == 0, result.stderr[-3000:]
        text = (work / "out" / "sub-51209" / "ses-1" / "nidm.ttl").read_text()
        blocks[seed] = [line for line in text.splitlines() if line.startswith("@prefix")]
    assert blocks["0"] == blocks["1"]
    assert "@prefix dcmitype: <http://purl.org/dc/dcmitype/> ." in blocks["0"]
    assert "@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> ." in blocks["0"]


def _process_with_stub_csv2nidm(tmp_path, logger, **patches):
    """process_subject on one T1w IQM JSON, without an input NIDM, with
    csv2nidm replaced by a stub writing a valid IQM graph; returns
    (ok, subject_dir)."""
    from unittest.mock import patch

    output_dir = tmp_path / "out"
    subject_dir = output_dir / "sub-51209" / "ses-1"
    mriqc_dir = _mriqc_tree(subject_dir, ["sub-51209_ses-1_run-1_T1w"])
    jsons = sorted(mriqc_dir.rglob("*.json"))

    def csv2nidm(**kwargs):
        Path(kwargs["output_ttl"]).write_text(iqm_nidm_ttl([str(j) for j in jsons]))
        return True

    with patch("src.run.convert_csv_to_nidm", side_effect=csv2nidm):
        with patch.multiple("src.run", **patches) if patches else _nullcontext():
            ok = process_subject(
                subject_id="51209", bids_dir=tmp_path, output_dir=output_dir,
                subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
                nidm_input_dir=tmp_path / "no_nidm", skip_mriqc=True,
                skip_nidm=False, logger=logger,
            )
    return ok, subject_dir


def _nullcontext():
    import contextlib
    return contextlib.nullcontext()


@pytest.mark.parametrize("umask, mode", [(0o022, 0o644), (0o002, 0o664), (0o077, 0o600)])
def test_nidm_ttl_gets_the_mode_of_a_new_file(tmp_path, logger, umask, mode):
    """nidm.ttl is written to a mkstemp file, which is created 0600; it must
    end up with the mode a newly created file gets under the umask, so that
    under the usual umasks it is readable by the people the derivative is
    shared with. (Under umask 077 that mode is 0600 too.)"""
    old = os.umask(umask)
    try:
        ok, subject_dir = _process_with_stub_csv2nidm(tmp_path, logger)
    finally:
        os.umask(old)
    assert ok is True
    assert (subject_dir / "nidm.ttl").stat().st_mode & 0o777 == mode


def test_nidm_ttl_is_the_checked_file_renamed_not_a_copy(tmp_path, logger):
    """The file whose records were checked becomes nidm.ttl by rename
    (os.replace, atomic), not by copying it, which a reader could see half
    written."""
    checked = {}

    def check_and_record(nidm_ttl, json_files):
        checked["inode"] = Path(nidm_ttl).stat().st_ino
        checked["path"] = Path(nidm_ttl)
        return check_iqm_records(nidm_ttl, json_files)

    ok, subject_dir = _process_with_stub_csv2nidm(
        tmp_path, logger, check_iqm_records=check_and_record)
    assert ok is True
    assert checked["path"].name != "nidm.ttl"
    assert (subject_dir / "nidm.ttl").stat().st_ino == checked["inode"]


def test_a_temporary_left_by_an_interrupted_run_is_removed(tmp_path, logger):
    """A run killed while converting leaves its `.nidm.XXXX.ttl` in the subject
    directory, which ships with it. The next conversion removes it first."""
    subject_dir = tmp_path / "out" / "sub-51209" / "ses-1"
    subject_dir.mkdir(parents=True)
    stale = subject_dir / ".nidm.k1ll3d00.ttl"
    stale.write_text("")
    ok, subject_dir = _process_with_stub_csv2nidm(tmp_path, logger)
    assert ok is True
    assert not stale.exists()
    assert [p.name for p in subject_dir.iterdir() if p.is_file()] == ["nidm.ttl"]


def test_start_cleanup_removes_only_hidden_nidm_temporaries(tmp_path, logger):
    """The cleanup deletes `.nidm.*.ttl` in the subject directory and nothing
    else: never nidm.ttl, other .ttl files, files in subdirectories (MRIQC's
    tree), or a symlink's target."""
    from src.run import _remove_interrupted_temporaries

    subject_dir = tmp_path / "sub-51209"
    (subject_dir / "mriqc").mkdir(parents=True)
    outside = tmp_path / "outside.ttl"
    outside.write_text("keep")
    temporaries = [subject_dir / ".nidm.k1ll3d00.ttl", subject_dir / ".nidm.0rphan00.ttl"]
    for path in temporaries:
        path.write_text("temporary")
    link = subject_dir / ".nidm.l1nk0000.ttl"
    link.symlink_to(outside)
    kept = [subject_dir / name for name in
            ("nidm.ttl", ".nidmnotes.ttl", "sub-51209.ttl", "nidm.ttl.bak", ".nidm.ttl.keep")]
    kept.append(subject_dir / "mriqc" / ".nidm.nested00.ttl")
    for path in kept:
        path.write_text("keep")

    _remove_interrupted_temporaries(subject_dir, logger)

    assert not any(p.exists() or p.is_symlink() for p in temporaries + [link])
    assert all(p.read_text() == "keep" for p in kept + [outside])


@pytest.mark.parametrize("previous", ["default", "ignore", "function"])
def test_sigterm_handler_is_restored_after_conversion(previous):
    """_exit_on_sigterm installs its handler only for the conversion and puts
    back whatever was there before, also when the block raises."""
    import signal
    from src.run import _exit_on_sigterm

    def custom(signum, frame):
        pass

    before = {"default": signal.SIG_DFL, "ignore": signal.SIG_IGN, "function": custom}[previous]
    saved = signal.signal(signal.SIGTERM, before)
    try:
        with _exit_on_sigterm():
            assert signal.getsignal(signal.SIGTERM) is not before
        assert signal.getsignal(signal.SIGTERM) is before
        with pytest.raises(RuntimeError):
            with _exit_on_sigterm():
                raise RuntimeError("conversion failed")
        assert signal.getsignal(signal.SIGTERM) is before
    finally:
        signal.signal(signal.SIGTERM, saved)


SIGTERMED_RUN = """
import logging, signal, subprocess, sys
# SIGTERM's disposition is inherited; start from the default a batch job has.
signal.signal(signal.SIGTERM, signal.SIG_DFL)
from pathlib import Path
from unittest.mock import patch
from src.run import process_subject
from tests.test_nidm_merge import _mriqc_tree

work, ready = Path(sys.argv[1]), Path(sys.argv[2])
subject_dir = work / "out" / "sub-51209" / "ses-1"
mriqc_dir = _mriqc_tree(subject_dir, ["sub-51209_ses-1_run-1_T1w"])

def csv2nidm_that_runs_long(**kwargs):
    assert list(subject_dir.glob(".nidm.*.ttl"))
    ready.write_text("converting")
    subprocess.run(["sleep", "60"], check=True)
    raise AssertionError("SIGTERM did not interrupt the conversion")

with patch("src.run.convert_csv_to_nidm", side_effect=csv2nidm_that_runs_long):
    process_subject(
        subject_id="51209", bids_dir=work, output_dir=work / "out",
        subject_dir=subject_dir, mriqc_dir=mriqc_dir, session_id="1",
        nidm_input_dir=work / "no_nidm", skip_mriqc=True, skip_nidm=False,
        logger=logging.getLogger("sigterm"))
"""


def test_sigterm_during_conversion_leaves_no_temporary(tmp_path):
    """SIGTERM (a SLURM time limit, scancel) used to end the app without
    cleanup, leaving `.nidm.XXXX.ttl` in the subject directory. A child
    process gets SIGTERM while it waits on a real subprocess in the
    conversion; it must exit 143 and leave no file in the subject directory."""
    import signal
    import subprocess
    import time

    root = Path(__file__).resolve().parent.parent
    ready = tmp_path / "ready"
    log = tmp_path / "child.log"
    # Output to a file, not a pipe: a `sleep` orphaned by the old behaviour
    # would hold a pipe open.
    with open(log, "w") as out:
        child = subprocess.Popen(
            [sys.executable, "-c", SIGTERMED_RUN, str(tmp_path), str(ready)],
            cwd=root, stdin=subprocess.DEVNULL, stdout=out, stderr=out)
    try:
        deadline = time.monotonic() + 120
        while not ready.exists():
            assert child.poll() is None, log.read_text()[-3000:]
            assert time.monotonic() < deadline, "the child never started converting"
            time.sleep(0.1)
        child.send_signal(signal.SIGTERM)
        child.wait(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    assert child.returncode == 143, (child.returncode, log.read_text()[-3000:])
    subject_dir = tmp_path / "out" / "sub-51209" / "ses-1"
    assert [p.name for p in subject_dir.iterdir() if p.is_file()] == []


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
