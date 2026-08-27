FROM nipreps/mriqc:25.0.0rc0

# Install minimal system dependencies (conda already provides Python/pip)
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# =======================================
# Environment Configuration
# =======================================
ENV PYTHONPATH=/opt:$PYTHONPATH
ENV PATH=/usr/local/bin:$PATH

# =======================================
# BIDS App Setup
# =======================================
# Copy application files to /opt
COPY . /opt/

# Install Python dependencies using conda/pip hybrid approach
# See requirements.txt for full dependency list
WORKDIR /opt

# Install conda-forge packages with micromamba, then pip packages
# Combining into single RUN reduces image layers
RUN micromamba install -n base -y -c conda-forge \
        pandas \
        rdflib \
        click \
        pybids && \
    pip install --no-cache-dir pynidm==4.2.3 nidmresults && \
    pip install --no-deps -e .

# =======================================
# Runtime Configuration
# =======================================
# Use the console script registered by setup.py ("mriqc-nidm=src.run:main").
# Do NOT invoke src/run.py as a file: it uses package-relative imports
# ("from . import __version__"), so `python3 /opt/src/run.py` fails with
# ImportError. This matches Singularity's %runscript, which is the entry point
# that is actually exercised on the cluster.
ENTRYPOINT ["mriqc-nidm"]
