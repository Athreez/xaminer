# Java 21 runner (TCK-0801). The base is pinned by digest: change it on purpose, bump
# RUNNER_VERSION in backend/app/platform/languages.py, then `make runners runners-check`.
FROM eclipse-temurin:21-jdk-alpine@sha256:b78a1d385da875588e21207f07dddf9a1418849971ae857fb24c8f3a7d441a72

# Student code is compiled and run as this user in /work, a small writable folder given at run
# time; everything else is read-only then. Temporary files go there too.
RUN adduser -D -H -u 10001 -s /sbin/nologin runner
ENV HOME=/work TMPDIR=/work JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=/work"
WORKDIR /work
USER 10001:10001
