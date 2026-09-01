# Recreate the legacy TensorFlow 1.x environment expected by the 2017 code.
FROM python:3.7.17-slim-bullseye

# Record the audited upstream revision in the image for provenance inspection.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REPRO_UPSTREAM_COMMIT=39a4089fe72ad9f055ed6fdb9746abdcfebc4d81

# Pin the build toolchain and numerical stack. These versions are intentionally
# old because modern NumPy/protobuf releases are incompatible with TensorFlow 1.15.
RUN python -m pip install --no-cache-dir \
        pip==23.1.2 \
        setuptools==40.6.3 \
        wheel==0.38.4 && \
    python -m pip install --no-cache-dir \
        numpy==1.18.5 \
        scipy==1.1.0 \
        networkx==2.2 \
        protobuf==3.20.3 \
        tensorflow==1.15.4

# ReproAgent mounts the frozen checkout read-only at this location.
WORKDIR /workspace
