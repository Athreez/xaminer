"""Build the runner images and load them into the sandbox engine (TCK-0801).

    make runners          # build on this machine, then load into sandbox-docker (stack up)
    make runners NO_LOAD=1  (or: python runners/build.py --no-load)

Student code runs on `sandbox-docker`, a separate Docker engine, so the images must be loaded
there; it has no access to this machine's images. Tags come from backend/app/platform/languages.py.
"""

import argparse
import subprocess
import sys

from smoke_test import ROOT, languages

COMPOSE = ["docker", "compose", "-f", str(ROOT / "deploy" / "docker-compose.yml")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-load", action="store_true", help="only build, don't load into the sandbox"
    )
    args = parser.parse_args()
    for runner in languages.RUNNERS:
        print(f"building {runner.image}", flush=True)
        subprocess.run(
            ["docker", "build", "-q", "-t", runner.image, str(ROOT / "runners" / runner.key)],
            check=True,
        )
    if args.no_load:
        return 0
    images = [runner.image for runner in languages.RUNNERS]
    print("loading into sandbox-docker", flush=True)
    save = subprocess.Popen(["docker", "save", *images], stdout=subprocess.PIPE)
    subprocess.run(
        [*COMPOSE, "exec", "-T", "sandbox-docker", "docker", "load"], stdin=save.stdout, check=True
    )
    assert save.stdout is not None
    save.stdout.close()
    return save.wait()


if __name__ == "__main__":
    sys.exit(main())
