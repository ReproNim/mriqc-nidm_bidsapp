"""restore_bids_labels on hand-written graphs: no csv2nidm needed."""

import csv
from pathlib import Path

import pytest
import rdflib
from rdflib import XSD, Literal

from src.nidm_converter.nidm_merge import IQMLabelError, restore_bids_labels

PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")
NIDM = rdflib.Namespace("http://purl.org/nidash/nidm#")
BIDS = rdflib.Namespace("http://bids.neuroimaging.io/")
MRIQC = rdflib.Namespace("https://mriqc.readthedocs.io/en/stable/")
NIIRI = rdflib.Namespace("http://iri.nidash.org/")

COLUMNS = ["subject_id", "ses", "task", "run", "source_url", "acq", "ce", "rec"]


def _record(name):
    """A csv2nidm IQM record, carrying the values csv2nidm gets wrong."""
    return (
        f'niiri:{name} a nidm:DerivativeCollection ; '
        f'prov:Location "/iqms/{name}.json"^^xsd:anyURI ; '
        'nidm:AcquisitionObject "1.0"^^xsd:string ; '
        'bids:session_number "1"^^xsd:string ; '
        'nidm:Task "1.0"^^xsd:string ; '
        'mriqc:acq_x "1.0"^^xsd:float .'
    )


def _write(tmp_path, record_names, rows):
    ttl = tmp_path / "iqms.ttl"
    ttl.write_text("\n".join([
        "@prefix bids: <http://bids.neuroimaging.io/> .",
        "@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> .",
        "@prefix nidm: <http://purl.org/nidash/nidm#> .",
        "@prefix niiri: <http://iri.nidash.org/> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        'mriqc:acq_x nidm:sourceVariable "acq" .',
        *(_record(n) for n in record_names),
    ]) + "\n")
    iqm_csv = tmp_path / "iqms.csv"
    with open(iqm_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for name, values in rows.items():
            writer.writerow({c: "" for c in COLUMNS} | values
                            | {"subject_id": "01", "source_url": f"/iqms/{name}.json"})
    return ttl, iqm_csv


def _values(ttl: Path, name):
    g = rdflib.Graph()
    g.parse(ttl, format="turtle")
    rec = NIIRI[name]
    return {
        prop: set(g.objects(rec, prop))
        for prop in (NIDM.AcquisitionObject, BIDS.session_number, NIDM.Task,
                     MRIQC.acq_x)
    }


def test_labels_are_written_in_their_restored_form(tmp_path):
    rows = {
        "a": {"run": "1a", "ses": "01", "task": "rest", "acq": "hires"},
        "b": {"run": "01", "ses": "1", "task": "1", "acq": "1"},
        "c": {"run": "", "ses": "NA", "task": "None", "acq": "nan"},
        "d": {},
    }
    ttl, iqm_csv = _write(tmp_path, rows, rows)

    assert restore_bids_labels(ttl, iqm_csv) == 4
    assert _values(ttl, "a") == {
        NIDM.AcquisitionObject: {Literal("1a")},
        BIDS.session_number: {Literal("01")},
        NIDM.Task: {Literal("rest")},
        MRIQC.acq_x: {Literal("hires")},
    }
    run_b = _values(ttl, "b")[NIDM.AcquisitionObject]
    assert [(str(v), v.datatype) for v in run_b] == [("1", XSD.integer)]
    assert _values(ttl, "b")[BIDS.session_number] == {Literal("1")}
    # NA-looking labels are labels; empty ones and the "None" task are none.
    assert _values(ttl, "c") == {
        NIDM.AcquisitionObject: set(),
        BIDS.session_number: {Literal("NA")},
        NIDM.Task: set(),
        MRIQC.acq_x: {Literal("nan")},
    }
    assert _values(ttl, "d") == {
        NIDM.AcquisitionObject: set(), BIDS.session_number: set(),
        NIDM.Task: set(), MRIQC.acq_x: set(),
    }


def test_record_without_csv_row_is_an_error(tmp_path):
    ttl, iqm_csv = _write(tmp_path, ["a", "b"], {"a": {"run": "1"}})
    before = ttl.read_text()

    expected = r"records without a row: \['/iqms/b.json'\]"
    with pytest.raises(IQMLabelError, match=expected):
        restore_bids_labels(ttl, iqm_csv)
    assert ttl.read_text() == before


def test_csv_row_without_record_is_an_error(tmp_path):
    ttl, iqm_csv = _write(tmp_path, ["a"], {"a": {"run": "1"}, "b": {"run": "2"}})
    before = ttl.read_text()

    expected = r"rows without a record: \['/iqms/b.json'\]"
    with pytest.raises(IQMLabelError, match=expected):
        restore_bids_labels(ttl, iqm_csv)
    assert ttl.read_text() == before
