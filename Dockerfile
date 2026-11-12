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
# Only /opt: the base image sets no PYTHONPATH, and `/opt:$PYTHONPATH` would
# end in an empty entry, which Python reads as the working directory.
ENV PYTHONPATH=/opt
ENV PATH=/usr/local/bin:$PATH

# =======================================
# BIDS App Setup
# =======================================
# Copy application files to /opt. COPY keeps the build context's file modes,
# so a file that is mode 600 in the checkout would be unreadable for a
# non-root --user; make the app's files readable by everyone.
COPY . /opt/
RUN chmod -R a+rX /opt/src /opt/requirements.txt /opt/setup.py /opt/setup.cfg /opt/VERSION

# Install Python dependencies using conda/pip hybrid approach
# See requirements.txt for full dependency list
WORKDIR /opt

# Install conda-forge packages with micromamba, then pip packages
# Combining into single RUN reduces image layers
# requirements.txt pins pynidm 5.0.0 and rdflib 7 in one resolvable set (PyNIDM
# 5.0.0 declares rdflib>=6.3.2,<8), so a single pip install is enough. The
# editable install is --no-deps so it cannot re-resolve anything already pinned.
RUN micromamba install -n base -y -c conda-forge \
        pandas \
        click \
        pybids && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-deps -e .

# PyNIDM 5.0.0 must import from this environment's site-packages, and the
# csv2nidm on PATH must run that same installation; src/check_pynidm.py exits
# non-zero otherwise. The same check runs in Singularity's %post.
RUN PYTHONPATH=/opt python /opt/src/check_pynidm.py

# Everything the app reads must be usable by a non-root --user, the same check
# Singularity runs at the end of %post.
RUN unreadable="$(find /opt/src /opt/requirements.txt /opt/setup.py /opt/setup.cfg /opt/VERSION \( -type f ! -perm -o=r \) -o \( -type d ! -perm -o=rx \))" && \
    if [ -n "$unreadable" ]; then \
        echo "ERROR: not readable by other users:" >&2; \
        echo "$unreadable" >&2; \
        exit 1; \
    fi

# =======================================
# Runtime Configuration
# =======================================
# Use the console script registered by setup.py ("mriqc-nidm=src.run:main").
# Do NOT invoke src/run.py as a file: it uses package-relative imports
# ("from . import __version__"), so `python3 /opt/src/run.py` fails with
# ImportError. This matches Singularity's %runscript, which is the entry point
# that is actually exercised on the cluster.
ENTRYPOINT ["mriqc-nidm"]

# The commit this image was built from (docker build --build-arg
# GIT_COMMIT=$(git rev-parse HEAD) ...). Declared last so that a new commit
# does not invalidate the cached layers above.
ARG GIT_COMMIT=unknown
# The version label overrides the base image's own (e.g. Ubuntu's 22.04).
LABEL org.opencontainers.image.version=0.1.4 \
      org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.source=https://github.com/ReproNim/mriqc-nidm_bidsapp
