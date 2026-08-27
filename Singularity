Bootstrap: docker
From: nipreps/mriqc:25.0.0rc0

%files
    ./src /opt/src
    ./requirements.txt /opt/requirements.txt
    ./setup.py /opt/setup.py
    ./setup.cfg /opt/setup.cfg
    ./VERSION /opt/VERSION

%post
    # Create opt directory for application code
    mkdir -p /opt

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

%environment
    # Add opt to Python path
    export PYTHONPATH=/opt:$PYTHONPATH
    # Add Python packages to path
    export PATH=/usr/local/bin:$PATH

%runscript
    # Execute the Python entry point (conda environment is already active)
    mriqc-nidm "$@"

%help
    MRIQC-NIDM BIDS App 0.1.0

    A BIDS Application that executes MRIQC (MRI Quality Control) on BIDS datasets
    and converts output to NIDM (Neuroimaging Data Model) format for improved
    interoperability.

    Version Information:
    - MRIQC-NIDM: 0.1.0
    - MRIQC: latest (from nipreps/mriqc:latest)
    - Base Image: nipreps/mriqc:latest

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
