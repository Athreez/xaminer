# Python 3.12 runner (TCK-0801). The base is pinned by digest: change it on purpose, bump
# RUNNER_VERSION in backend/app/platform/languages.py, then `make runners runners-check`.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

# Student code runs as this user in /work, a small writable folder given at run time; everything
# else is read-only then. No .pyc files, and output isn't held back in a buffer.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner
ENV HOME=/work TMPDIR=/work PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
USER 10001:10001
