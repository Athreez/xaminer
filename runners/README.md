# Language runners

One image per language students can use: `cpp17`, `java21`, `python312`, `node22`. Each
`<key>/Dockerfile` starts from an official image pinned by digest and adds a non-root user; student
code is compiled and run in `/work`, a small writable folder, with everything else read-only.

The tag, file name and compile/run commands live in `backend/app/platform/languages.py` (the
`language` table holds the same values).

```sh
make runners         # build, then load into sandbox-docker (stack up), where student code runs
make runners-check   # hello-world in every language, here and in the sandbox, sandboxed
```

To change an image: edit its Dockerfile, bump `RUNNER_VERSION` in `languages.py`, add a migration
that updates the `language` table, then run both commands.
