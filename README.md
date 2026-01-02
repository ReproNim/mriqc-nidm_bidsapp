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
- **Package name:** `mriqc-nidm_bidsapp` (installed via pip)
- **CLI command:** `mriqc-nidm` (shorter for usability)
- **Output directory:** `mriqc-nidm_bidsapp/` (created in output folder)
- **Container name:** `mriqc-nidm-bidsapp-<version>`

The CLI command (`mriqc-nidm`) is intentionally shorter than the package/output names for better user experience.

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

```
output_dir/
└── mriqc-nidm_bidsapp/          # All outputs packaged together
    ├── mriqc/                   # MRIQC outputs (JSON, HTML, figures)
    │   └── sub-{id}/
    │       └── [ses-{label}/]   # Session subdirectory if applicable
    └── nidm/                    # NIDM outputs (TTL files)
        ├── dataset_description.json
        └── sub-{id}/
            └── [ses-{label}/]   # Session subdirectory if applicable
                └── sub-{id}[_ses-{label}].ttl
```

The output follows BIDS derivatives structure with subject/session-specific subdirectories. The app automatically copies existing NIDM files before augmentation, ensuring originals are never overwritten.

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
