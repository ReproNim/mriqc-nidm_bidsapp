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
Functional and diffusion images are not gated.
"""

import logging
from collections import namedtuple
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from bids.layout import parse_file_entities

logger = logging.getLogger("mriqc-nidm.inputs")

DEFAULT_MAX_VOXEL_SIZE = 2.0  # mm, any dimension

ANAT_SUFFIXES = ("T1w", "T2w")

# MRIQC's own anatomical query (niworkflows DEFAULT_BIDS_QUERIES) only takes
# magnitude images; phase images are never rated, so they are never gated.
_QUERIED_PARTS = ("mag", None)

# Entities MRIQC sets itself from its command line and default query.
_RESERVED_ENTITIES = {"subject", "session", "datatype", "suffix", "extension"}

# filters: {lower-case suffix: pybids query}, for --bids-filter-file.
# dropped: suffixes with images but none within the limit.
# too_coarse: (Path, voxel size tuple) pairs over the limit.
AnatGate = namedtuple("AnatGate", ["filters", "dropped", "too_coarse"])


def voxel_size(path: Path) -> Tuple[float, ...]:
    """Voxel size in mm of the first three dimensions, from the header only."""
    import nibabel as nib

    return tuple(round(float(z), 3) for z in nib.load(str(path)).header.get_zooms()[:3])


def _entities(path: Path) -> Dict[str, object]:
    return {
        key: int(value) if isinstance(value, int) else value
        for key, value in parse_file_entities(str(path)).items()
        if key not in _RESERVED_ENTITIES
    }


def anat_images(
    bids_dir: Path, subject: str, session: Optional[str], suffix: str
) -> List[Path]:
    """The images MRIQC would rate for one suffix, as it would query them.

    Without a session MRIQC takes every session of the subject, so this does
    too.
    """
    subject_dir = Path(bids_dir) / f"sub-{subject}"
    if session:
        anat_dirs = [subject_dir / f"ses-{session}" / "anat"]
    else:
        anat_dirs = [subject_dir / "anat", *sorted(subject_dir.glob("ses-*/anat"))]
    images = []
    for anat_dir in anat_dirs:
        if not anat_dir.is_dir():
            continue
        for path in sorted(anat_dir.iterdir()):
            if not path.name.endswith((f"_{suffix}.nii", f"_{suffix}.nii.gz")):
                continue
            if _entities(path).get("part") not in _QUERIED_PARTS:
                continue
            images.append(path)
    return images


def selecting_filter(keep: Sequence[Path], drop: Sequence[Path]) -> Dict[str, list]:
    """A pybids query selecting every image in ``keep`` and none in ``drop``.

    Each entity is limited to the values it takes in ``keep``, None standing
    for "entity absent" as in pybids. That selects all of ``keep`` by
    construction; it can also select an image in ``drop`` that only mixes
    values of kept images (acq-a_run-2 when acq-a_run-1 and acq-b_run-2 are
    kept). Then no entity filter separates them and ValueError is raised
    rather than letting MRIQC rate a dropped image.
    """
    entities = {path: _entities(path) for path in [*keep, *drop]}
    names = sorted(set().union(*entities.values()))
    query = {
        name: sorted(
            {entities[path].get(name) for path in keep},
            key=lambda value: (value is not None, str(value)),
        )
        for name in names
    }
    selected = [
        path
        for path in drop
        if all(entities[path].get(name) in values for name, values in query.items())
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
) -> AnatGate:
    """Split one subject/session's T1w/T2w images by ``max_voxel_size``.

    An image whose header cannot be read is kept: MRIQC reports the read
    error itself, which is clearer than a skip.
    """
    filters, dropped, too_coarse = {}, [], []
    for suffix in ANAT_SUFFIXES:
        keep, drop = [], []
        for path in anat_images(bids_dir, subject, session, suffix):
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
        if keep:
            filters[suffix.lower()] = selecting_filter(keep, drop)
        else:
            dropped.append(suffix)
    return AnatGate(filters, dropped, too_coarse)
