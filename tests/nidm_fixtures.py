"""Small NIDM graphs shaped like bidsmri2nidm and csv2nidm output.

The input graph mirrors what bidsmri2nidm (PyNIDM 4.5.0) writes for a BIDS
dataset: anatomical acquisition objects carry no run or task, only the
image filename, while functional ones also carry ``nidm:AcquisitionObject``
(the run) and ``nidm:Task``. Sessions carry no session number.
"""

PREFIXES = """\
@prefix dct: <http://purl.org/dc/terms/> .
@prefix ndar: <https://ndar.nih.gov/api/datadictionary/v2/dataelement/> .
@prefix nfo: <http://www.semanticdesktop.org/ontologies/2007/03/22/nfo#> .
@prefix nidm: <http://purl.org/nidash/nidm#> .
@prefix niiri: <http://iri.nidash.org/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sio: <http://semanticscience.org/ontology/sio.owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix mriqc: <https://mriqc.readthedocs.io/en/stable/> .
"""

# (session, image stem) for one UCLA_Long-shaped subject
UCLA_IMAGES = [
    ("1", "sub-51209_ses-1_acq-hires_run-1_T1w"),
    ("1", "sub-51209_ses-1_run-1_T1w"),
    ("1", "sub-51209_ses-1_task-rest_run-1_bold"),
    ("2", "sub-51209_ses-2_acq-hires_run-1_T1w"),
    ("2", "sub-51209_ses-2_run-1_T1w"),
    ("2", "sub-51209_ses-2_task-rest_run-1_bold"),
]


def input_nidm_ttl(subject="51209", images=UCLA_IMAGES):
    """Turtle for a bidsmri2nidm-like experiment graph."""
    out = [
        PREFIXES,
        "niiri:project a nidm:Project, prov:Activity .",
        f'niiri:person a prov:Agent, prov:Person ; '
        f'ndar:src_subject_id "{subject}"^^xsd:string .',
    ]
    for ses in sorted({ses for ses, _ in images}):
        out.append(
            f"niiri:session-{ses} a nidm:Session, prov:Activity ; "
            "dct:isPartOf niiri:project ."
        )
    for i, (ses, stem) in enumerate(images):
        datatype = "func" if stem.endswith("_bold") else "anat"
        func = (
            ' nidm:AcquisitionObject 1 ; nidm:Task "rest"^^xsd:string ;'
            if datatype == "func"
            else ""
        )
        out.append(
            f"niiri:acq-act-{i} a nidm:Acquisition, prov:Activity ; "
            f"dct:isPartOf niiri:session-{ses} ; "
            "prov:qualifiedAssociation [ a prov:Association ; "
            "prov:agent niiri:person ; prov:hadRole sio:Subject ] ."
        )
        out.append(
            f"niiri:acq-obj-{i} a nidm:AcquisitionObject, prov:Entity ;{func} "
            f'nfo:filename "bids::raw/sub-{subject}/ses-{ses}/{datatype}/'
            f'{stem}.nii.gz"^^xsd:string ; '
            f"prov:wasGeneratedBy niiri:acq-act-{i} ."
        )
    return "\n".join(out) + "\n"


def iqm_nidm_ttl(json_paths, subject="51209"):
    """Turtle shaped like a standalone `csv2nidm -derivative` result.

    One derivative activity and DerivativeCollection per IQM JSON, each with
    its own freshly minted subject Person, all part of a new Project.
    """
    out = [
        PREFIXES,
        "niiri:iqm-project a nidm:Project, prov:Activity .",
        'niiri:iqm-collection a prov:Collection, prov:Entity ; '
        'nfo:filename "iqms.csv" .',
        "niiri:mriqc-agent a nidm:SoftwareAgent, prov:Agent .",
        "niiri:export a prov:Activity ; prov:used niiri:iqm-project .",
    ]
    for i, path in enumerate(json_paths):
        out.append(
            f'niiri:iqm-person-{i} a prov:Agent, prov:Person ; '
            f'ndar:src_subject_id "{subject}"^^xsd:string .'
        )
        out.append(
            f"niiri:der-act-{i} a prov:Activity ; dct:isPartOf niiri:iqm-project ; "
            "prov:qualifiedAssociation [ a prov:Association ; "
            f"prov:agent niiri:iqm-person-{i} ; prov:hadRole sio:Subject ], "
            "[ a prov:Association ; prov:agent niiri:mriqc-agent ; "
            "prov:hadRole nidm:NIDM_0000164 ] ."
        )
        out.append(
            f"niiri:der-ent-{i} a prov:Entity ; "
            "rdfs:type nidm:DerivativeCollection ; "
            f'prov:Location "{path}"^^xsd:anyURI ; '
            f'mriqc:cjv_x "0.{i + 1}"^^xsd:float ; '
            f"prov:wasGeneratedBy niiri:der-act-{i} ."
        )
    return "\n".join(out) + "\n"
