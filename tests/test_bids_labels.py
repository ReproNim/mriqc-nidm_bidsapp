"""BIDS labels of IQM records reach NIDM as written, through the real csv2nidm.

csv2nidm re-reads the IQM CSV with pandas, which turns a label column that
looks numeric into numbers: a run column mixing images without a run (T1w)
and run-1/run-2 images becomes float, so run 1 was written as "1.0". The
same happens to numeric session, task and acq labels.
"""

import json
import logging
import shutil
from pathlib import Path

import pytest
import rdflib
from rdflib import XSD

from src.nidm_converter.data import get_mriqc_dictionary
from src.nidm_converter.json_to_csv import convert_mriqc_json_to_csv
from src.run import _write_iqm_nidm
from tests.nidm_fixtures import input_nidm_ttl
from tests.test_nidm_merge import _run, _write

PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")
NIDM = rdflib.Namespace("http://purl.org/nidash/nidm#")
BIDS = rdflib.Namespace("http://bids.neuroimaging.io/")

needs_csv2nidm = pytest.mark.skipif(
    shutil.which("csv2nidm") is None, reason="csv2nidm (PyNIDM) not installed"
)


@pytest.fixture
def logger():
    return logging.getLogger("test_bids_labels")


def _record_values(ttl: Path, prop):
    """Map each IQM JSON basename to the (text, datatype) values of prop on
    its record. Records are the entities whose prov:Location is a .json."""
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    values = {}
    for ent, loc in g.subject_objects(PROV.Location):
        if str(loc).endswith(".json"):
            values[str(loc).rsplit("/", 1)[-1]] = sorted(
                (str(o), o.datatype) for o in g.objects(ent, prop)
            )
    return values


def _acq_property(ttl: Path):
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    (prop,) = [s for s, o in g.subject_objects(NIDM.sourceVariable) if str(o) == "acq"]
    return prop


MIXED_RUN_STEMS = [
    "sub-51209_ses-1_T1w",
    "sub-51209_ses-1_task-rest_run-1_bold",
    "sub-51209_ses-1_task-rest_run-2_bold",
]


@needs_csv2nidm
@pytest.mark.parametrize("with_input", [False, True], ids=["new", "input-nidm"])
def test_mixed_run_column_keeps_run_numbers(tmp_path, logger, with_input):
    """A run-less T1w next to run-1/run-2 BOLD: runs stay 1 and 2, not 1.0"""
    nidm_dir = tmp_path / "nidm"
    if with_input:
        _write(nidm_dir / "sub-51209" / "ses-1" / "nidm.ttl",
               input_nidm_ttl(images=[("1", s) for s in MIXED_RUN_STEMS]))
    ok, ttl = _run(tmp_path, MIXED_RUN_STEMS, nidm_dir, logger)

    assert ok is True
    assert _record_values(ttl, NIDM.AcquisitionObject) == {
        "sub-51209_ses-1_T1w.json": [],
        "sub-51209_ses-1_task-rest_run-1_bold.json": [("1", XSD.integer)],
        "sub-51209_ses-1_task-rest_run-2_bold.json": [("2", XSD.integer)],
    }
    assert '"1.0"' not in ttl.read_text()
    assert '"2.0"' not in ttl.read_text()


@needs_csv2nidm
def test_numeric_session_task_and_acq_labels_keep_their_text(tmp_path, logger):
    """ses-01 stays "01"; task-1 and acq-1 stay "1", not 1, 1.0 or xsd:float"""
    stems = [
        "sub-01_ses-01_T1w",
        "sub-01_ses-01_task-1_acq-1_run-1_bold",
        "sub-01_ses-01_task-1_run-2_bold",
    ]
    csvs = []
    for stem in stems:
        json_file = tmp_path / f"{stem}.json"
        iqms = {"cjv": 0.5} if stem.endswith("_T1w") else {"fd_mean": 0.1}
        json_file.write_text(json.dumps(
            {**iqms, "provenance": {"software": "mriqc", "version": "25.0.0"}}
        ))
        csv_path, software_csv = convert_mriqc_json_to_csv(
            json_file, tmp_path / f"{stem}.csv", logger
        )
        csvs.append(csv_path)
    ttl = tmp_path / "nidm.ttl"
    _write_iqm_nidm(csvs, software_csv, get_mriqc_dictionary(), tmp_path,
                    None, ttl, logger)

    t1w, bold1, bold2 = (f"{s}.json" for s in stems)
    assert _record_values(ttl, BIDS.session_number) == {
        name: [("01", None)] for name in (t1w, bold1, bold2)
    }
    assert _record_values(ttl, NIDM.Task) == {
        t1w: [], bold1: [("1", None)], bold2: [("1", None)],
    }
    assert _record_values(ttl, _acq_property(ttl)) == {
        t1w: [], bold1: [("1", None)], bold2: [],
    }
    assert _record_values(ttl, NIDM.AcquisitionObject) == {
        t1w: [], bold1: [("1", XSD.integer)], bold2: [("2", XSD.integer)],
    }


# The run fragment of PyNIDM's run lookups (nidm/linkml/experiment/query.py,
# GetAcquisitionEntityFromSubjectSessionRun): the run as a bare number,
# ``nidm:AcquisitionObject {run}``. Only the fragment: those functions return
# acquisitions, never IQM records.
RUN_PATTERN = """
    prefix nidm: <http://purl.org/nidash/nidm#>
    prefix prov: <http://www.w3.org/ns/prov#>
    select ?loc where { ?e nidm:AcquisitionObject %d ; prov:Location ?loc . }
"""


def _locations_with_run(ttl: Path, run: int):
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    return sorted(str(r.loc).rsplit("/", 1)[-1] for r in g.query(RUN_PATTERN % run))


@needs_csv2nidm
def test_run_pattern_finds_the_iqm_record(tmp_path, logger):
    """The pattern `nidm:AcquisitionObject 1` finds run 1's IQM record"""
    ok, ttl = _run(tmp_path, MIXED_RUN_STEMS, tmp_path / "nidm", logger)

    assert ok is True
    assert _locations_with_run(ttl, 1) == ["sub-51209_ses-1_task-rest_run-1_bold.json"]
    assert _locations_with_run(ttl, 2) == ["sub-51209_ses-1_task-rest_run-2_bold.json"]


SESSION_JOIN = """
    prefix bids: <http://bids.neuroimaging.io/>
    prefix nidm: <http://purl.org/nidash/nidm#>
    prefix prov: <http://www.w3.org/ns/prov#>
    select ?loc ?ses where {
        ?ses a nidm:Session ; bids:session_number ?label .
        ?rec prov:Location ?loc ; bids:session_number ?label .
    }
"""


@needs_csv2nidm
def test_session_label_joins_bidsmri2nidm_session(tmp_path, logger):
    """An IQM record's session number joins the Session bidsmri2nidm wrote"""
    from nidm.linkml.experiment.tools.bidsmri2nidm import _lit

    json_file = tmp_path / "sub-01_ses-01_T1w.json"
    json_file.write_text(json.dumps(
        {"cjv": 0.5, "provenance": {"software": "mriqc", "version": "25.0.0"}}
    ))
    csv_path, software_csv = convert_mriqc_json_to_csv(
        json_file, tmp_path / "iqm.csv", logger
    )
    ttl = tmp_path / "nidm.ttl"
    _write_iqm_nidm([csv_path], software_csv, get_mriqc_dictionary(), tmp_path,
                    None, ttl, logger)

    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    # The triple bidsmri2nidm writes for session ses-01 (bidsmri2nidm.py, the
    # imaging-session loop), with its own literal helper.
    session = rdflib.URIRef("http://iri.nidash.org/session-01")
    g.add((session, rdflib.RDF.type, NIDM.Session))
    g.add((session, BIDS.session_number, _lit("01")))

    rows = [(str(r.loc).rsplit("/", 1)[-1], r.ses) for r in g.query(SESSION_JOIN)]
    assert rows == [("sub-01_ses-01_T1w.json", session)]
