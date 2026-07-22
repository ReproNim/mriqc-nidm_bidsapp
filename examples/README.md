# BABS examples

`babs-mriqc-nidm-bids-study.yaml` targets the configurable BIDS-study layout
introduced by PennLINC/babs PR #369. The BABS analysis DataLad dataset is the
project directory itself and internal RIA stores live under `.babs/`.

Replace the input, compute-space, and cluster placeholders before use. For a
session-level BABS project, uncomment `$SESSION_SELECTION_FLAG`; leave it
commented for subject-level projects because BABS only defines `$sesid` in
session-wise job scripts.

The container remains compatible with BABS's legacy layout. Omit
`analysis_path`, `input_ria_path`, and `output_ria_path` to retain the default
`analysis/`, `input_ria/`, and `output_ria/` directories.
