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
# Entrypoint that expects input/output paths as arguments
ENTRYPOINT ["mriqc-nidm"]
