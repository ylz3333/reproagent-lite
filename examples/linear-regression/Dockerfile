# Minimal offline image for the trusted linear-regression fixture.
FROM python:3.11-slim

# The runner bind-mounts the example here as a read-only source directory.
WORKDIR /workspace

# This default documents intended usage; registered task commands take priority.
CMD ["python", "experiment.py"]
