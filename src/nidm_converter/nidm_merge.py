#!/usr/bin/env python
"""
Attach MRIQC IQM records to an existing NIDM graph.

csv2nidm can append derivative data to an existing NIDM file itself (its
-nidm mode), but it links each derivative to an acquisition by matching the
CSV's session/task/run against the acquisition metadata. bidsmri2nidm
records run and task only on functional images, so in that mode csv2nidm
drops T1w IQM rows that have no run and links T1w rows that do have one to
the BOLD acquisition with the same run number. Both happen with exit
status 0.

The app therefore lets csv2nidm write all IQM records of a job into a new
graph (where it keeps every row) and attaches that graph to the input NIDM
here, linking each IQM record to the acquisition whose image has the same
BIDS name as the IQM JSON. An IQM record that matches no acquisition, or
more than one, is an error rather than a guess.
"""

import csv
import logging
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.util import guess_format

from .json_to_csv import IMAGE_ENTITIES

PROV = Namespace("http://www.w3.org/ns/prov#")
NIDM = Namespace("http://purl.org/nidash/nidm#")
DCT = Namespace("http://purl.org/dc/terms/")
SIO = Namespace("http://semanticscience.org/ontology/sio.owl#")
BIDS = Namespace("http://bids.neuroimaging.io/")
# The IQM properties' namespace (json_to_csv's software url). csv2nidm 4.x
# binds the prefix mriqc to it. csv2nidm 5.0.0 builds its output with
# rdflib's Graph.__add__, which binds the prefixes of both operands by
# iterating a set: the project graph it parsed back names this namespace ns1,
# its CDE graph names it mriqc, and whichever the process's string hash seed
# puts last wins, so the same input gives ns1: or mriqc: from run to run.
# Every graph the app writes goes through serialize_nidm, which binds mriqc.
MRIQC = Namespace("https://mriqc.readthedocs.io/en/stable/")
# Bound by bidsmri2nidm as dcmitype; rdflib combines graphs' bindings from a
# set, so csv2nidm's output and the merge named it dcmitype or dctypes
# depending on the string hash seed.
DCMITYPE = Namespace("http://purl.org/dc/dcmitype/")
# csv2nidm writes rdfs:type (not a term of the closed RDFS namespace) on the
# entities of a new file.
RDFS_TYPE = URIRef(str(RDFS) + "type")
NFO_FILENAME = URIRef(
    "http://www.semanticdesktop.org/ontologies/2007/03/22/nfo#filename"
)

_IMAGE_SUFFIXES = (".nii.gz", ".nii", ".json")


class IQMLinkError(RuntimeError):
    """An IQM record could not be tied to exactly one input acquisition."""


def _image_stem(name: str) -> str:
    """BIDS name of an image or IQM file without directory or extension."""
    name = name.rsplit("/", 1)[-1]
    for suffix in _IMAGE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _iqm_records(graph: Graph) -> Dict[URIRef, str]:
    """Map each IQM DerivativeCollection entity to its prov:Location.

    csv2nidm types the entity with rdfs:type when it writes a new file and
    with rdf:type when it appends, so both are accepted.
    """
    records = {}
    for ent, loc in graph.subject_objects(PROV.Location):
        if not str(loc).endswith(".json"):
            continue
        typed = (ent, RDF.type, NIDM.DerivativeCollection) in graph or (
            ent, RDFS_TYPE, NIDM.DerivativeCollection
        ) in graph
        if typed:
            records[ent] = str(loc)
    return records


def fix_csv2nidm_types(ttl: Path) -> int:
    """
    Type csv2nidm's IQM records and software agent with rdf:type, in place.

    PyNIDM's GetDerivativesDataForSubject only follows derivative activities
    whose agent has rdf:type prov:SoftwareAgent. csv2nidm (PyNIDM 4.5.0, and
    upstream at the time of writing) never gives the MRIQC agent that type
    (only its own export-provenance agents get it): with -out it
    gives the MRIQC agent and the IQM DerivativeCollection entities their
    NIDM types through rdfs:type, a predicate neither RDF nor RDFS defines,
    and with -nidm it types the agent rdf:type nidm:SoftwareAgent only.
    Either way the query returns no MRIQC data. Every rdfs:type triple
    becomes rdf:type, and each nidm:SoftwareAgent also gets
    prov:SoftwareAgent. A graph whose agents already have prov:SoftwareAgent
    and that has no rdfs:type is not rewritten.

    Args:
        ttl: Turtle file written by csv2nidm; rewritten when anything changes

    Returns:
        Number of triples added
    """
    graph = Graph()
    graph.parse(ttl, format="turtle")
    before = len(graph)
    added = 0
    for s, o in list(graph.subject_objects(RDFS_TYPE)):
        graph.remove((s, RDFS_TYPE, o))
        if (s, RDF.type, o) not in graph:
            graph.add((s, RDF.type, o))
            added += 1
    for agent in list(graph.subjects(RDF.type, NIDM.SoftwareAgent)):
        if (agent, RDF.type, PROV.SoftwareAgent) not in graph:
            graph.add((agent, RDF.type, PROV.SoftwareAgent))
            added += 1
    if added or len(graph) != before:
        graph.serialize(destination=str(ttl), format="turtle")
    return added


def _run_literal(label: str) -> Literal:
    """The run as csv2nidm writes it from a run column with no empty cell:
    xsd:int, or the text when it is not a whole number."""
    try:
        return Literal(int(label), datatype=XSD.int)
    except ValueError:
        return Literal(label, datatype=XSD.string)


def restore_bids_labels(iqm_ttl: Path, iqm_csv: Path) -> int:
    """
    Record each IQM record's BIDS labels as the IQM CSV holds them, in place.

    csv2nidm re-reads the CSV with pandas and keeps only the subject id
    column as text, so pandas reads any other label column that looks
    numeric as numbers. A run column that mixes images without a run
    (T1w) and images with one becomes float, and csv2nidm writes run 1 as
    the text "1.0"; a session label 01 becomes "1"; a numeric acq, ce or rec
    label becomes xsd:float 1.0, or xsd:integer 1 when no cell is empty.

    Each record is matched to its CSV row by prov:Location, which csv2nidm
    sets from the row's source_url, and gets:

    - run as nidm:AcquisitionObject, xsd:int: what csv2nidm writes when the
      run column has no empty cell, and the integer PyNIDM's schema gives
      this property;
    - ses as bids:session_number and task as nidm:Task, xsd:string, the
      label text unchanged;
    - acq, ce and rec under their data-element property, xsd:string, the
      label text unchanged (the data dictionary's valueType).

    An empty label, and the "None" task of anatomical images, gets no triple,
    as csv2nidm does. Records without a CSV row are left as they are.

    Args:
        iqm_ttl: Turtle file written by csv2nidm; rewritten when anything changes
        iqm_csv: The CSV csv2nidm converted (combine_iqm_csvs)

    Returns:
        Number of records changed
    """
    with open(iqm_csv, newline="") as f:
        rows = {row.get("source_url"): row for row in csv.DictReader(f)}

    graph = Graph()
    graph.parse(iqm_ttl, format="turtle")
    entity_properties = {
        entity: [
            cde for cde, name in graph.subject_objects(NIDM.sourceVariable)
            if str(name) == entity
        ]
        for entity in IMAGE_ENTITIES
    }

    changed = 0
    for record, location in _iqm_records(graph).items():
        row = rows.get(location)
        if row is None:
            continue
        task = row.get("task", "")
        wanted = [
            (NIDM.AcquisitionObject,
             _run_literal(row["run"]) if row.get("run") else None),
            (BIDS.session_number,
             Literal(row["ses"], datatype=XSD.string) if row.get("ses") else None),
            (NIDM.Task,
             Literal(task, datatype=XSD.string) if task not in ("", "None") else None),
        ]
        for entity in IMAGE_ENTITIES:
            label = row.get(entity, "")
            for prop in entity_properties[entity]:
                wanted.append(
                    (prop, Literal(label, datatype=XSD.string) if label else None)
                )

        record_changed = False
        for prop, literal in wanted:
            current = set(graph.objects(record, prop))
            target = {literal} if literal is not None else set()
            if current != target:
                graph.remove((record, prop, None))
                if literal is not None:
                    graph.add((record, prop, literal))
                record_changed = True
        changed += record_changed

    if changed:
        graph.serialize(destination=str(iqm_ttl), format="turtle")
    return changed


def serialize_nidm(graph: Graph, destination: Path) -> None:
    """Write graph to destination as Turtle, the IQM properties' namespace
    named mriqc and the DCMI types namespace dcmitype, whatever prefixes the
    graph had bound to them: rdflib picks between two prefixes for one
    namespace by the string hash seed, so the same run would otherwise write
    different text."""
    graph.bind("mriqc", MRIQC, override=True, replace=True)
    graph.bind("dcmitype", DCMITYPE, override=True, replace=True)
    graph.serialize(destination=str(destination), format="turtle")


def write_iqm_nidm(iqm_ttl: Path, output_ttl: Path) -> None:
    """Write csv2nidm's IQM graph to output_ttl as the subject's NIDM (the
    case without an input NIDM), through serialize_nidm."""
    graph = Graph()
    graph.parse(iqm_ttl, format="turtle")
    serialize_nidm(graph, output_ttl)


def _participant(graph: Graph, activity) -> Optional[URIRef]:
    """Agent associated with an activity in the sio:Subject role."""
    for assoc in graph.objects(activity, PROV.qualifiedAssociation):
        if graph.value(assoc, PROV.hadRole) == SIO.Subject:
            return graph.value(assoc, PROV.agent)
    return None


def merge_iqms_into_nidm(
    input_ttl: Path,
    iqm_ttl: Path,
    output_ttl: Path,
    logger: Optional[logging.Logger] = None,
    source: Optional[Path] = None,
) -> int:
    """
    Attach the IQM records in iqm_ttl to the NIDM graph in input_ttl.

    For each IQM record, the acquisition object in input_ttl whose
    nfo:filename has the same BIDS name as the IQM JSON is located; the
    derivative activity then gets prov:used to that acquisition activity,
    becomes part of the input project, and is associated with the input's
    participant. The Project, Collection and per-row Person nodes that
    csv2nidm mints for a new file are dropped so the subject is not
    duplicated.

    Args:
        input_ttl: Existing NIDM graph (e.g. from bidsmri2nidm)
        iqm_ttl: Graph written by `csv2nidm -derivative` without -nidm
        output_ttl: Where to write the merged graph (may equal input_ttl)
        logger: Optional logger instance
        source: The input NIDM as found in the NIDM input directory, named in
            errors when input_ttl is a working copy of it (default input_ttl)

    Returns:
        Number of IQM records linked

    Raises:
        IQMLinkError: If any IQM record matches zero or several acquisitions.
            Nothing is written in that case.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    source = source or input_ttl
    base = Graph()
    # Parsed by extension. The app passes the input NIDM it found, read only,
    # and refuses a non-Turtle input before getting here, so in the app this
    # is Turtle.
    base.parse(input_ttl, format=guess_format(str(input_ttl)) or "turtle")
    iqm = Graph()
    iqm.parse(iqm_ttl, format="turtle")

    acquisitions: Dict[str, List[URIRef]] = {}
    for obj, filename in base.subject_objects(NFO_FILENAME):
        if (obj, RDF.type, NIDM.AcquisitionObject) in base:
            acquisitions.setdefault(_image_stem(str(filename)), []).append(obj)

    scaffold_projects = set(iqm.subjects(RDF.type, NIDM.Project))
    scaffold_persons = set(iqm.subjects(RDF.type, PROV.Person))
    scaffold_collections = set(iqm.subjects(RDF.type, PROV.Collection))

    problems = []
    input_project = None
    records = _iqm_records(iqm)
    for ent, location in sorted(records.items(), key=lambda kv: kv[1]):
        stem = _image_stem(location)
        matches = acquisitions.get(stem, [])
        if len(matches) != 1:
            problems.append(
                f"{stem}: {len(matches)} acquisitions have this image name"
            )
            continue
        acq_activity = base.value(matches[0], PROV.wasGeneratedBy)
        session = base.value(acq_activity, DCT.isPartOf)
        project = base.value(session, DCT.isPartOf) if session else None
        participant = _participant(base, acq_activity)
        if acq_activity is None or project is None or participant is None:
            problems.append(
                f"{stem}: the acquisition lacks its activity, "
                f"session/project or participant"
            )
            continue
        input_project = input_project or project

        for activity in iqm.objects(ent, PROV.wasGeneratedBy):
            iqm.add((activity, PROV.used, acq_activity))
            for old in scaffold_projects:
                if (activity, DCT.isPartOf, old) in iqm:
                    iqm.remove((activity, DCT.isPartOf, old))
                    iqm.add((activity, DCT.isPartOf, project))
            for assoc in iqm.objects(activity, PROV.qualifiedAssociation):
                if iqm.value(assoc, PROV.hadRole) == SIO.Subject:
                    iqm.set((assoc, PROV.agent, participant))
        logger.debug(f"Linked IQM record {stem} to {acq_activity}")

    if problems:
        raise IQMLinkError(
            f"Cannot link MRIQC IQM records to the input NIDM {source}: "
            + "; ".join(problems)
            + ". The input NIDM must describe the images MRIQC rated: it has "
            "to come from this BIDS dataset. Regenerate it from this dataset "
            "with bidsmri2nidm."
        )

    # Anything else that pointed at csv2nidm's own project (its export
    # provenance record) now points at the input project.
    for old in scaffold_projects:
        for s, p in list(iqm.subject_predicates(old)):
            iqm.remove((s, p, old))
            if input_project is not None:
                iqm.add((s, p, input_project))
    for node in scaffold_projects | scaffold_persons | scaffold_collections:
        iqm.remove((node, None, None))
        iqm.remove((None, None, node))

    merged = base + iqm
    for graph in (base, iqm):
        for prefix, namespace in graph.namespaces():
            merged.bind(prefix, namespace, override=False)
    serialize_nidm(merged, output_ttl)

    logger.info(
        f"Linked {len(records)} MRIQC IQM record(s) to input acquisitions "
        f"in {output_ttl.name}"
    )
    return len(records)


def check_iqm_records(nidm_ttl: Path, json_files: Iterable[Path]) -> List[str]:
    """
    Check that nidm_ttl holds exactly one IQM record per IQM JSON.

    Records are matched on prov:Location, which csv2nidm sets from the
    source_url column (the IQM JSON path), so records already present in an
    input NIDM from an earlier run are not counted.

    Args:
        nidm_ttl: NIDM graph written for the job
        json_files: IQM JSON files the job converted

    Returns:
        A list of problems; empty when every JSON has exactly one record
    """
    graph = Graph()
    graph.parse(nidm_ttl, format="turtle")
    counts = Counter(_iqm_records(graph).values())

    problems = []
    for json_file in json_files:
        n = counts.get(str(json_file), 0)
        if n != 1:
            problems.append(f"{Path(json_file).name}: {n} records in NIDM")
    return problems


__all__ = [
    "IQMLinkError",
    "check_iqm_records",
    "fix_csv2nidm_types",
    "merge_iqms_into_nidm",
    "restore_bids_labels",
]
