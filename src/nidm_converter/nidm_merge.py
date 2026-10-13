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

import logging
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from rdflib import RDF, RDFS, Graph, Namespace, URIRef
from rdflib.util import guess_format

PROV = Namespace("http://www.w3.org/ns/prov#")
NIDM = Namespace("http://purl.org/nidash/nidm#")
DCT = Namespace("http://purl.org/dc/terms/")
SIO = Namespace("http://semanticscience.org/ontology/sio.owl#")
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
    # Parsed by extension. The app always passes its nidm.ttl copy and refuses
    # a non-Turtle input before getting here, so in the app this is Turtle.
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
    merged.serialize(destination=str(output_ttl), format="turtle")

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
    "merge_iqms_into_nidm",
]
