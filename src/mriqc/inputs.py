"""Anatomical images too coarse for MRIQC to rate.

MRIQC's anatomical workflow assumes a whole-brain, roughly isotropic image.
ABIDE II UCLA_Long's ``acq-hires`` T1w is a 1.5 x 1.5 x 4 mm partial-coverage
slab: MRIQC 25 crashes on it ("Input inhomogeneity-corrected data seem empty")
and the whole session then fails, although the same session's 1 mm T1w is
rated fine. The sibling ANTs and FreeSurfer apps skip such images with the
same ``--max-voxel-size`` limit (default 2 mm, any dimension).

MRIQC cannot filter on voxel size, so the gate reads the T1w/T2w headers
itself and hands MRIQC a ``--bids-filter-file`` that selects exactly the
images within the limit. A suffix with no image within the limit is removed
from MRIQC's ``--modalities`` instead, since no entity filter selects nothing.
Functional and diffusion images are not gated, but when a suffix is removed
the gate checks that MRIQC still has images to rate, since MRIQC itself stops
on an empty query with a message that does not name the cause.

Which images a filter selects is decided by pybids, on a layout indexed the
way MRIQC 25 indexes the dataset (mriqc/config.py, execution.init), never by
comparing values here: pybids reads an empty value list as "no constraint",
matches "1" and "01" against run 1, and resolves metadata filters from the
sidecars, so a hand-made answer can disagree with what MRIQC is then given.
"""

import logging
import re
from collections import namedtuple
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from bids import BIDSLayout, BIDSLayoutIndexer
from bids.layout import Query

logger = logging.getLogger("mriqc-nidm.inputs")

DEFAULT_MAX_VOXEL_SIZE = 2.0  # mm, any dimension

ANAT_SUFFIXES = ("T1w", "T2w")

# MRIQC's own query per modality (niworkflows 1.10 DEFAULT_BIDS_QUERIES).
_DEFAULT_QUERIES = {
    "T1w": {"datatype": "anat", "suffix": "T1w", "part": ["mag", None]},
    "T2w": {"datatype": "anat", "suffix": "T2w", "part": ["mag", None]},
    "bold": {"datatype": "func", "suffix": "bold", "part": ["mag", None]},
    "dwi": {"suffix": "dwi"},
}

# Entities MRIQC sets itself from its command line and default query. The
# session is MRIQC's only when --session-id is given; otherwise a filter may
# use it to tell sessions apart.
_RESERVED_ENTITIES = {"subject", "datatype", "suffix", "extension"}

# filters: {lower-case suffix: pybids query}, for --bids-filter-file.
# dropped: suffixes with images but none within the limit.
# too_coarse: (Path, voxel size tuple) pairs over the limit.
# left: the requested modalities MRIQC still has images for; only checked
#   when a suffix is dropped, otherwise every requested modality.
AnatGate = namedtuple("AnatGate", ["filters", "dropped", "too_coarse", "left"])


def voxel_size(path: Path) -> Tuple[float, ...]:
    """Voxel size in mm of the first three dimensions, from the header only."""
    import nibabel as nib

    return tuple(round(float(z), 3) for z in nib.load(str(path)).header.get_zooms()[:3])


def mriqc_layout(bids_dir: Path, subject: str) -> BIDSLayout:
    """The dataset as MRIQC 25 indexes it for ``--participant-label subject``."""
    ignore = [
        re.compile(r"^(?!/sub-(" + subject + "))"),
        re.compile(
            r"^/sub-[a-zA-Z0-9]+(/ses-[a-zA-Z0-9]+)?/"
            r"(beh|fmap|pet|perf|meg|eeg|ieeg|micr|nirs)"
        ),
        re.compile(r"^.+(?<!(_T1w|_T2w|bold|_dwi))\.(json|nii|nii\.gz)$"),
    ]
    return BIDSLayout(
        str(Path(bids_dir).absolute()),
        indexer=BIDSLayoutIndexer(validate=False, ignore=ignore),
    )


def mriqc_selects(
    layout: BIDSLayout, subject: str, session: Optional[str], suffix: str, query: dict
) -> List[Path]:
    """The ``suffix`` images (T1w, T2w, bold or dwi) MRIQC selects with ``query``.

    niworkflows' collect_data: the default query updated with the filter,
    which may also override the session.
    """
    get_kwargs = {
        "return_type": "file",
        "subject": subject,
        "session": session or Query.OPTIONAL,
        "extension": [".nii", ".nii.gz"],
    }
    found = layout.get(**{**get_kwargs, **_DEFAULT_QUERIES[suffix], **query})
    return sorted(Path(f) for f in found)


def selecting_filter(
    entities: Dict[Path, dict],
    keep: Sequence[Path],
    drop: Sequence[Path],
    with_session: bool = False,
) -> Dict[str, list]:
    """A pybids query selecting every image in ``keep`` and none in ``drop``.

    ``entities`` maps each image to its pybids entities. Each entity is
    limited to the values it takes in ``keep``, None standing for "entity
    absent" as in pybids. That selects all of ``keep`` by construction; it
    can also select an image in ``drop`` that only mixes values of kept
    images (acq-a_run-2 when acq-a_run-1 and acq-b_run-2 are kept). Then no
    entity filter separates them and ValueError is raised rather than letting
    MRIQC rate a dropped image. ``with_session`` lets the filter use the
    session, for a run without --session-id.
    """
    reserved = _RESERVED_ENTITIES if with_session else _RESERVED_ENTITIES | {"session"}
    usable = {
        path: {
            key: int(value) if isinstance(value, int) else value
            for key, value in entities[path].items()
            if key not in reserved
        }
        for path in [*keep, *drop]
    }
    names = sorted(set().union(*usable.values()))
    query = {
        name: sorted(
            {usable[path].get(name) for path in keep},
            key=lambda value: (value is not None, str(value)),
        )
        for name in names
    }
    selected = [
        path
        for path in drop
        if all(usable[path].get(name) in values for name, values in query.items())
    ]
    if selected:
        raise ValueError(
            "No BIDS entity filter keeps "
            + ", ".join(path.name for path in keep)
            + " without also keeping "
            + ", ".join(path.name for path in selected)
        )
    return query


def gate_anat_inputs(
    bids_dir: Path,
    subject: str,
    session: Optional[str],
    max_voxel_size: float,
    modalities: Sequence[str] = ANAT_SUFFIXES,
    user_filters: Optional[dict] = None,
    task: Optional[object] = None,
) -> AnatGate:
    """Split one subject/session's T1w/T2w images by ``max_voxel_size``.

    Only suffixes in ``modalities`` are gated, and within them only the images
    ``user_filters`` (a --bids-filter-file's content, lower-case keys) already
    selects. A returned filter is the user's with entity constraints added
    (or narrowed) so that it selects exactly the user's images within the
    limit, checked with pybids.

    ``task`` is MRIQC's --task-id, which niworkflows sets on the bold query
    after applying the filters, so it overrides a filter's task; it only
    matters for ``left``.

    An image whose header cannot be read is kept: MRIQC reports the read
    error itself, which is clearer than a skip.
    """
    user_filters = user_filters or {}
    suffixes = [suffix for suffix in ANAT_SUFFIXES if suffix in modalities]
    filters, dropped, too_coarse = {}, [], []
    if not suffixes:
        return AnatGate(filters, dropped, too_coarse, list(modalities))
    layout = mriqc_layout(bids_dir, subject)
    for suffix in suffixes:
        user_query = user_filters.get(suffix.lower(), {})
        keep, drop = [], []
        for path in mriqc_selects(layout, subject, session, suffix, user_query):
            try:
                zooms = voxel_size(path)
            except Exception as e:
                logger.warning(f"Could not read the header of {path.name}: {e}")
                keep.append(path)
                continue
            if max(zooms) > max_voxel_size:
                drop.append(path)
                too_coarse.append((path, zooms))
            else:
                keep.append(path)
        if not drop:
            continue
        if not keep:
            dropped.append(suffix)
            continue
        # Separate the kept images from the coarse ones only and add that to
        # the user's filter, which goes on excluding what it excluded (also
        # by metadata, which no entity filter could reproduce).
        entities = {
            path: layout.get_file(str(path)).get_entities(metadata=False)
            for path in [*keep, *drop]
        }
        query = {
            **user_query,
            **selecting_filter(entities, keep, drop, with_session=session is None),
        }
        selected = mriqc_selects(layout, subject, session, suffix, query)
        if selected != sorted(keep):
            raise ValueError(
                f"The {suffix} filter {query} selects "
                + (", ".join(p.name for p in selected) or "nothing")
                + " instead of " + ", ".join(p.name for p in keep)
            )
        filters[suffix.lower()] = query
    left = [
        modality
        for modality in modalities
        if modality not in dropped
        and (
            not dropped
            or mriqc_selects(
                layout, subject, session, modality,
                {
                    **filters.get(modality.lower(), user_filters.get(modality.lower(), {})),
                    **({"task": task} if task and modality == "bold" else {}),
                },
            )
        )
    ]
    return AnatGate(filters, dropped, too_coarse, left)
