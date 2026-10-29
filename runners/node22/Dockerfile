# Node.js 22 runner (TCK-0801). The base is pinned by digest: change it on purpose, bump
# RUNNER_VERSION in backend/app/platform/languages.py, then `make runners runners-check`.
FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da

# Student code lives in /work (owned by this user) and runs as this user; at run time everything
# else is read-only and temporary files go to /tmp.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner
ENV HOME=/tmp TMPDIR=/tmp NODE_ENV=production
RUN mkdir -p /work && chown 10001:10001 /work
WORKDIR /work
USER 10001:10001
