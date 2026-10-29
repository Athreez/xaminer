# Python 3.12 runner (TCK-0801). The base is pinned by digest: change it on purpose, bump
# RUNNER_VERSION in backend/app/platform/languages.py, then `make runners runners-check`.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

# Student code lives in /work (owned by this user) and runs as this user; at run time everything
# else is read-only and temporary files go to /tmp. No .pyc files, no output buffering.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner
ENV HOME=/tmp TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN mkdir -p /work && chown 10001:10001 /work
WORKDIR /work
USER 10001:10001
