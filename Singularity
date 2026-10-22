Bootstrap: docker
From: nipreps/mriqc:25.0.0rc0

# The commit this image was built from, read back with
# `apptainer inspect --labels <image>`. Pass it at build time:
#   apptainer build --build-arg GIT_COMMIT=$(git rev-parse HEAD) ...
# Without --build-arg the label reads "unknown".
# org.opencontainers.image.version is this app's version. It is written in
# %post, not %labels: without --force, %labels does not replace a label the
# base image already sets, so the base's own (e.g. Ubuntu's 22.04) would
# show through.
# tests/test_version.py checks it against the app version.
%arguments
    GIT_COMMIT=unknown

%labels
    org.opencontainers.image.revision {{ GIT_COMMIT }}
    org.opencontainers.image.source https://github.com/ReproNim/mriqc-nidm_bidsapp

%files
    ./src /opt/src
    ./requirements.txt /opt/requirements.txt
    ./setup.py /opt/setup.py
    ./setup.cfg /opt/setup.cfg
    ./VERSION /opt/VERSION

%post
    # Fail the build on the first failing command. %post is one scriptlet whose
    # exit status is its last command's, so without this a failed pip install
    # would be hidden by the permission check that now follows it.
    set -e

    # Unless the build uses --force, Apptainer keeps an inherited label over the
    # same key in %labels (it warns "already exists ... not overwriting"); a
    # label written here replaces it either way. SingularityCE sets only
    # SINGULARITY_LABELS, hence the fallback.
    echo "org.opencontainers.image.version 0.1.2" >> "${APPTAINER_LABELS:-$SINGULARITY_LABELS}"

    # Create opt directory for application code
    mkdir -p /opt

    # %files keeps each file's mode from the checkout it was copied from, and a
    # SIF keeps the builder's uid. A file that is mode 600 there is unreadable
    # for every other account running the image: the 0.1.0 image shipped
    # src/mriqc/__init__.py and src/validators.py that way, so `import src.run`
    # failed for anyone but its builder. a+rX: files readable, directories
    # traversable, nothing made executable.
    chmod -R a+rX /opt/src /opt/requirements.txt /opt/setup.py /opt/setup.cfg /opt/VERSION

    # Install system dependencies (minimal - conda already provides Python/pip)
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        git \
        build-essential \
        && apt-get clean && \
        rm -rf /var/lib/apt/lists/*

    # Install Python dependencies using conda/pip hybrid approach
    # See requirements.txt for full dependency list
    cd /opt

    # Install conda-forge packages with micromamba, then pip packages
    # NOTE the two-step pip install. pynidm 4.5.0 *declares* rdflib>=6.3.2,<6.4,
    # but it ships an oxigraph-backed store whose oxrdflib requires rdflib<8 and
    # actually wants rdflib 7. Installing requirements first and then
    # force-upgrading rdflib deliberately overrides pynidm's stale pin -- a
    # single resolved install cannot express this (uv refuses it outright).
    # Same order as freesurfer-nidm_bidsapp.
    micromamba install -n base -y -c conda-forge \
        pandas \
        click \
        pybids && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --upgrade 'rdflib>=7.0.0,<8' && \
    pip install --no-deps -e .

    # Last step: everything this recipe put under /opt must be usable by
    # whoever runs the image, not only by the account that built it.
    unreadable="$(find /opt/src /opt/requirements.txt /opt/setup.py /opt/setup.cfg /opt/VERSION \( -type f ! -perm -o=r \) -o \( -type d ! -perm -o=rx \))"
    if [ -n "$unreadable" ]; then
        echo "ERROR: not readable by other users (the image only works for its builder):" >&2
        echo "$unreadable" >&2
        exit 1
    fi

%environment
    # Add opt to Python path
    export PYTHONPATH=/opt:$PYTHONPATH
    # Add Python packages to path
    export PATH=/usr/local/bin:$PATH

%runscript
    # Execute the Python entry point (conda environment is already active)
    mriqc-nidm "$@"

%help
    MRIQC-NIDM BIDS App 0.1.2

    A BIDS Application that executes MRIQC (MRI Quality Control) on BIDS datasets
    and converts output to NIDM (Neuroimaging Data Model) format for improved
    interoperability.

    Version Information:
    - MRIQC-NIDM: 0.1.2
    - MRIQC: 25.0.0rc0
    - Base Image: nipreps/mriqc:25.0.0rc0

    Usage:
      singularity run -B [workdir] [container] [bids_dir] [output_dir] participant [options]

    Required Arguments:
      bids_dir          Path to BIDS dataset directory
      output_dir        Path to output directory
      participant       Analysis level (only 'participant' supported currently)

    Optional Arguments:
      --participant-label LABEL [LABEL ...]
                        Subject label(s) to process (without 'sub-' prefix)
      --nidm-input-dir PATH
                        Override default NIDM input location (default: BIDS/../NIDM/)
      --skip-mriqc      Skip MRIQC execution, use existing output
      --mriqc-output-dir PATH
                        Use existing MRIQC output directory
      --skip-nidm-conversion
                        Run MRIQC only, skip NIDM conversion
      -v, --verbose     Enable verbose logging

    Example - Full workflow:
      singularity run -B $PWD mriqc-nidm_bidsapp.sif \\
        $PWD/inputs/BIDS \\
        $PWD/outputs \\
        participant \\
        --participant-label 01 02

    Example - BABS-style label (with sub- prefix):
      singularity run -B $PWD mriqc-nidm_bidsapp.sif \\
        $PWD/inputs/BIDS \\
        $PWD/outputs \\
        participant \\
        --participant-label sub-01

    Example - Specifying working directory for cluster:
      singularity run -B $PWD mriqc-nidm_bidsapp.sif \\
        $PWD/inputs/BIDS \\
        $PWD/outputs \\
        participant \\
        --participant-label 01 \\
        --work-dir /scratch/mriqc_work

    Example - With existing NIDM to augment:
      # Input structure:
      # /data/
      #   ├── BIDS/
      #   └── NIDM/  (existing NIDM files)
      #       └── sub-01/nidm.ttl

      singularity run -B /data mriqc-nidm_bidsapp.sif \\
        /data/BIDS \\
        /data/outputs \\
        participant \\
        --participant-label 01

    Example - Convert existing MRIQC output:
      singularity run -B $PWD mriqc-nidm_bidsapp.sif \\
        $PWD/inputs/BIDS \\
        $PWD/outputs \\
        participant \\
        --skip-mriqc \\
        --mriqc-output-dir $PWD/existing_mriqc

    For more information:
      https://github.com/yibeichan/mriqc-nidm_bidsapp
