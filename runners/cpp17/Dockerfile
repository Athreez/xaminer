# C++17 runner (TCK-0801). The base is pinned by digest: change it on purpose, bump
# RUNNER_VERSION in backend/app/platform/languages.py, then `make runners runners-check`.
FROM gcc:14@sha256:435c3cbc2ad1c25fbc1684c367808ff0ca2035a1bed56734a40165ab5cd7e3bd

# Student code is compiled and run as this user in /work, a small writable folder given at run
# time; everything else is read-only then. Temporary files go there too.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner
ENV HOME=/work TMPDIR=/work
WORKDIR /work
USER 10001:10001
