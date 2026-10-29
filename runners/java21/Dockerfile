# Java 21 runner (TCK-0801). The base is pinned by digest: change it on purpose, bump
# RUNNER_VERSION in backend/app/platform/languages.py, then `make runners runners-check`.
FROM eclipse-temurin:21-jdk-alpine@sha256:b78a1d385da875588e21207f07dddf9a1418849971ae857fb24c8f3a7d441a72

# Student code lives in /work (owned by this user, so a job's volume mounted there is writable for
# the compile step) and runs as this user; at run time everything else is read-only and temporary
# files go to /tmp, a small private folder.
RUN adduser -D -H -u 10001 -s /sbin/nologin runner
ENV HOME=/tmp TMPDIR=/tmp
RUN mkdir -p /work && chown 10001:10001 /work
WORKDIR /work
USER 10001:10001
