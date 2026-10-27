# MRIQC-NIDM BIDS App

A BIDS App that runs MRIQC quality control on neuroimaging data and converts the outputs to NIDM (Neuroimaging Data Model) format for improved interoperability and integration with existing analysis provenance graphs.

## Main Features

- **MRIQC Execution**: Runs MRIQC quality control on BIDS neuroimaging datasets
- **NIDM Conversion**: Converts MRIQC JSON outputs to NIDM format (TTL/JSON-LD)
- **NIDM Augmentation**: Can augment existing NIDM files with new MRIQC metrics
- **Multi-session Support**: Handles both single and multi-session datasets
- **Standards Compliant**: Follows BIDS App specification and BIDS derivatives structure

## Repository Structure

```
.
├── src/
│   ├── __init__.py                   # Package version and metadata
│   ├── run.py                        # CLI entry point
│   ├── utils.py                      # Utility functions
│   ├── validators.py                 # Input validation
│   ├── mriqc/                        # MRIQC wrapper module
│   │   ├── inputs.py                 # --max-voxel-size gate on T1w/T2w inputs
│   │   └── mriqc_runner.py           # MRIQC execution wrapper
│   └── nidm_converter/               # NIDM conversion package
│       ├── nidm_converter.py         # NIDM detection and copying
│       ├── json_to_csv.py            # MRIQC JSON to CSV conversion
│       ├── csv_to_nidm.py            # CSV to NIDM wrapper
│       ├── nidm_utils.py             # NIDM utilities
│       └── data/                     # Data files
│           ├── mriqc_dictionary_v1.csv
│           └── mriqc_software_metadata.csv
├── tests/                            # Comprehensive test suite
├── setup.py                          # Package configuration
├── requirements.txt                  # Python dependencies
├── Singularity                       # Singularity/Apptainer definition
└── Dockerfile                        # Docker definition
```

## Naming Conventions

This repository uses consistent naming:
- **Repository name:** `mriqc-nidm_bidsapp` (this GitHub repository)
- **Package name:** `mriqc-nidm` (installed via pip)
- **CLI command:** `mriqc-nidm` (shorter for usability)
- **Output directory:** `sub-{id}/` per subject, directly in the output folder
- **Container name:** `mriqc-nidm_bidsapp-<version>`

The package name (`mriqc-nidm`) is shorter for usability, while output directory matches repository name.

## Installation

### Using Apptainer

1. Build the container:
```bash
apptainer build --fakeroot --build-arg GIT_COMMIT=$(git rev-parse HEAD) mriqc-nidm_bidsapp.sif Singularity
```

> **Building on a cluster:** if your site's apptainer module exports
> `APPTAINER_BINDPATH` (MIT ORCD sets `/orcd,/nfs`), unset it for the build.
> Those paths exist on the host but not inside the base image, so `%post` dies
> with `destination /nfs doesn't exist in container`. It is only needed at run
> time:
> ```bash
> env -u APPTAINER_BINDPATH apptainer build --fakeroot --build-arg GIT_COMMIT=$(git rev-parse HEAD) mriqc-nidm_bidsapp.sif Singularity
> ```

2. Run the container — the first positional argument is the **BIDS** directory:
```bash
apptainer run -B $PWD mriqc-nidm_bidsapp.sif \
  /path/to/bids /path/to/output participant --participant-label 01
```

### Using Docker

1. Build the container:
```bash
docker build --build-arg GIT_COMMIT=$(git rev-parse HEAD) -t mriqc-nidm_bidsapp .
```

2. Run the container:
```bash
docker run -v /path/to/mriqc/output:/data -v /path/to/output:/out mriqc-nidm_bidsapp /data /out participant
```

## Usage

The app runs MRIQC quality control and converts outputs to NIDM format. It can augment existing NIDM files with MRIQC metrics, making it suitable for integrating QC data into existing analysis provenance graphs.

```bash
mriqc-nidm <bids_dir> <output_dir> participant \
  --participant-label <subject_id> \
  --nidm-input-dir <nidm_dir> \
  [options]

### Required Arguments

- `bids_dir`: Path to BIDS dataset directory
- `output_dir`: Path to output directory
- `analysis_level`: Must be `participant`
- `--participant-label`: Subject ID(s) to process (without 'sub-' prefix)
- `--nidm-input-dir`: Directory containing existing NIDM files to augment

### Optional Arguments

- `--session-label`: Session label(s) to process (without 'ses-' prefix)
- `--skip-mriqc`: Skip MRIQC execution, use existing output
- `--mriqc-output-dir`: Use existing MRIQC output directory
- `--skip-nidm-conversion`: Run MRIQC only, skip NIDM conversion
- `--max-voxel-size`: Leave out T1w/T2w images with any voxel dimension
  above this, in mm (off by default); see [Anatomical images MRIQC cannot rate](#anatomical-images-mriqc-cannot-rate)
- `-v, --verbose`: Enable verbose output
- `--version`: Show version information

### Output Structure

Everything this app produces for a subject lives under that subject's own
directory, with `nidm.ttl` beside the analysis results:

```
output_dir/
├── dataset_description.json     # derivative root, written once
└── sub-{id}/                    # [/ses-{label}/] when --session-label is given
    ├── nidm.ttl                 # input NIDM + this app's MRIQC metrics
    ├── processing_summary.json  # with --max-voxel-size: images left out
    └── mriqc/                   # MRIQC outputs (IQM JSON, HTML reports, logs)
        └── sub-{id}/
            └── [ses-{label}/]
                └── {anat,func}/*.json
```

The NIDM product is **always** named `nidm.ttl`. Subject identity is carried by
the containing directory, never by the filename — this is what lets outputs from
several apps merge into one study-wide derivative tree without collisions. It
matches the sibling `freesurfer-nidm` and `fsl-nidm` BIDSapps.

`dataset_description.json` sits at the derivative root, deliberately *outside*
the per-subject directory: under BABS that directory is what gets zipped and
shipped, so a copy inside it would be duplicated into every subject's zip.

The app copies existing NIDM files before augmentation, so originals are never
overwritten.

Each image MRIQC rates gets its own record of IQMs in `nidm.ttl`. Besides subject, session, task and run, a record carries the
image's BIDS `acq`, `ce` and `rec` labels when its filename has them, so two
images of one run (e.g. `sub-X_ses-1_run-1_T1w` and
`sub-X_ses-1_acq-mprage_run-1_T1w`) can be told apart. The labels are annotated
in `mriqc_dictionary_v1.csv`; csv2nidm needs a dictionary row for every IQM
CSV column it annotates, and stops to prompt on stdin for any column without
one.

#### Anatomical images MRIQC cannot rate

MRIQC 25 stops with "Input inhomogeneity-corrected data seem empty" when the
tissue segmentation of a T1w or T2w image finds no white matter it is
confident about, and the whole session then fails. An image whose contrast
it cannot separate into tissues can do that, and so can a thin slab. ABIDE II
UCLA_Long's `acq-hires` T1w (1.5 x 1.5 x 4 mm) is one: it fails because of its
contrast, not its voxel size, while the same session's 1 mm T1w is rated.

MRIQC cannot be told to skip such an image, but when a dataset's failing
images are its thick-slice ones, `--max-voxel-size` leaves them out (off by
default; use 2 for UCLA_Long, the limit the sibling ANTs and FreeSurfer apps
use). Before running MRIQC the app then reads the header of every T1w and
T2w image of the subject or session and leaves out any with a voxel
dimension above the limit:

- Only the modalities MRIQC is asked to run (`-m`/`--modalities`, default
  all) are checked, and with a filter file of your own only the images it
  selects.
- If some images of a suffix are within the limit, MRIQC gets a
  `--bids-filter-file` that selects exactly those, checked with pybids the
  way MRIQC queries it. For that suffix your filter is kept and narrowed by
  BIDS entities; your filters for other suffixes are passed on unchanged.
  A `--run-id` you pass is written into that filter file rather than given
  to MRIQC, which would otherwise apply it over the filter. If no BIDS
  entity can tell the images within the limit from the others, the subject
  fails, naming them.
- If no image of a suffix is within the limit, that suffix is removed from
  MRIQC's `--modalities`, and the session gets IQMs for its other images
  only. If MRIQC would then have no image left to rate, the subject fails
  without starting MRIQC, with an error naming the images that were too
  coarse. A bold or dwi series too short for MRIQC (which drops them after
  selecting) still counts as an image left, so MRIQC starts and fails.
- A T1w or T2w git-annex file whose content has not been fetched (a broken
  symlink, or a pointer file in an unlocked dataset) fails the subject; run
  `datalad get` first. BABS fetches the
  subject before running the app.
- With a filter file that sets `session` for any modality, MRIQC drops the
  session from every modality's query, which the check does not model: an
  image of another session can then reach MRIQC unchecked.

The images left out, with their voxel sizes, are listed in
`sub-{id}/[ses-{label}/]processing_summary.json` under `inputs_too_coarse`,
images whose header could not be read (and so were not checked) under
`inputs_not_checked`, and a suffix with nothing left under
`modalities_not_run`. Functional and diffusion images are not checked.

#### Input NIDM lookup

For a subject (and session, under `--session-label`) the app uses the first
of these that exists in the NIDM input directory (`--nidm-input-dir`, default
`<bids_dir>/../NIDM`):

1. `sub-{id}/ses-{label}/nidm.ttl`
2. `sub-{id}/ses-{label}/sub-{id}_ses-{label}.ttl`
3. `sub-{id}/nidm.ttl`
4. any `*.ttl` in `sub-{id}/`
5. `nidm.ttl` (dataset-level file)

Input NIDM must be Turtle. When `sub-{id}/` has no `*.ttl` but has a
`*.jsonld` or `*.json-ld` file, step 4 picks that file and the job fails with
an error naming it, instead of reading it.

#### How IQM records are written

All IQM JSONs of a job go to csv2nidm as one multi-row CSV, which it writes
into a new graph. When there is an input NIDM, the app attaches that graph to
it: each IQM record's derivative activity gets `prov:used` pointing at the
acquisition whose image has the same BIDS name as the IQM JSON, and is
associated with the input's participant and project.

Under `--session-label`, only IQM JSONs whose filename carries that session
(`ses-{label}`) are written. A `--mriqc-output-dir` holding several sessions
of a subject therefore still gives each session's `nidm.ttl` its own records
only; the others are skipped and listed in the log.

csv2nidm's own append mode (`-nidm`) is not used. It matches a derivative to
an acquisition by session/task/run, and bidsmri2nidm records run and task only
for functional images, so in that mode T1w IQMs were either dropped or linked
to a BOLD acquisition with the same run number, with exit status 0.

PyNIDM's own `GetDerivativesDataForSubject` only finds derivatives whose
software agent has `rdf:type prov:SoftwareAgent`. csv2nidm (PyNIDM 4.5.0) never
gives the MRIQC agent that type, so the query found no MRIQC data in the result.
csv2nidm also gives the IQM records and the agent their NIDM types through
`rdfs:type`, a predicate neither RDF nor RDFS defines. Before writing
`nidm.ttl`, the app rewrites those triples as `rdf:type` and adds
`prov:SoftwareAgent` to the agent. Output from a csv2nidm that already types the
agent `prov:SoftwareAgent` (incf-nidash/PyNIDM#457) is not rewritten.

A job fails (non-zero exit) when an IQM record matches no acquisition or
several, or when `nidm.ttl` does not end up with exactly one IQM record per
IQM JSON. When the app runs MRIQC itself, the job also fails when MRIQC exits
non-zero or no IQM JSON is found for a subject. That subject is not converted
to NIDM, even if MRIQC wrote some IQM JSONs before failing.

This catches MRIQC failures, not every missing IQM:
- MRIQC itself skips runs it cannot process (BOLD runs under 5 volumes, DWI
  under 7, anatomical images with more than one volume), logs a warning and
  exits 0, so those runs have no IQMs and the job still succeeds. If every
  run of a modality is dropped, MRIQC 25 crashes instead, and the job fails.
- With `--skip-mriqc` or `--mriqc-output-dir` there is no MRIQC exit status to
  check, and the app converts the IQM JSONs it finds.
- A re-run into an existing output directory also reads IQM JSONs left by an
  earlier run.

**Running under BABS:** pair this layout with `zip_foldernames: {${subid}: "<version>"}`
so the zip's top-level folder is `sub-{id}` and results unzip straight into
`<derivative_name>/sub-{id}/...`.

### Examples

**Process single subject:**
```bash
mriqc-nidm /data/bids /data/output participant \
  --participant-label 001 \
  --nidm-input-dir /data/NIDM
```

**Process subject with specific session:**
```bash
mriqc-nidm /data/bids /data/output participant \
  --participant-label 001 \
  --session-label baseline \
  --nidm-input-dir /data/NIDM
```

**Use existing MRIQC outputs:**
```bash
mriqc-nidm /data/bids /data/output participant \
  --participant-label 001 \
  --nidm-input-dir /data/NIDM \
  --skip-mriqc \
  --mriqc-output-dir /data/existing_mriqc
```

**Run MRIQC only (skip NIDM conversion):**
```bash
mriqc-nidm /data/bids /data/output participant \
  --participant-label 001 \
  --skip-nidm-conversion
```

## Development

Install in development mode:
```bash
pip install -e .
```

Run tests:
```bash
pytest tests/ -v
```

## Citation

If you use this tool, please cite:
- MRIQC: https://doi.org/10.1371/journal.pone.0184661
- NIDM: http://nidm.nidash.org/

## License

MIT License - See [LICENSE](LICENSE) file for details.

## Links

- Repository: https://github.com/ReproNim/mriqc-nidm_bidsapp
- Issues: https://github.com/ReproNim/mriqc-nidm_bidsapp/issues
