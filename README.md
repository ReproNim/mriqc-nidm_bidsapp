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
apptainer build mriqc-nidm_bidsapp.sif Singularity
```

2. Run the container:
```bash
apptainer run mriqc-nidm_bidsapp.sif /path/to/mriqc/output /path/to/output participant
```

### Using Docker

1. Build the container:
```bash
docker build -t mriqc-nidm_bidsapp .
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

- Repository: https://github.com/sensein/mriqc-nidm_bidsapp
- Issues: https://github.com/sensein/mriqc-nidm_bidsapp/issues
