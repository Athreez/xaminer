"""Point the demo at this laptop's Wi-Fi address: HTTPS certificate hosts and email links.

    python scripts/demo_https.py [--ip 192.168.1.20]

Finds the address other devices on the network reach this laptop at (or takes --ip), then sets
in deploy/.env:  CERT_HOSTS=localhost,127.0.0.1,<ip>  and  PUBLIC_BASE_URL=https://<ip>:<port>.
Run `make up` afterwards; the web container makes a new certificate for the new hosts.
"""

import argparse
import re
import socket
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / "deploy" / ".env"


def lan_ip() -> str:
    """The address this laptop uses on its network (no traffic is sent: UDP connect only)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))
        return str(s.getsockname()[0])


def set_values(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
        text = (
            pattern.sub(line, text) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
        )
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ip", help="use this address instead of the one found")
    args = parser.parse_args()
    if not ENV.exists():
        raise SystemExit("deploy/.env is missing: copy deploy/.env.example first (see README).")
    ip = args.ip or lan_ip()
    text = ENV.read_text(encoding="utf-8")
    port = re.search(r"^WEB_HTTPS_PORT=(\d+)", text, re.MULTILINE)
    https_port = port.group(1) if port else "8443"
    url = f"https://{ip}" + ("" if https_port == "443" else f":{https_port}")
    ENV.write_text(
        set_values(text, {"CERT_HOSTS": f"localhost,127.0.0.1,{ip}", "PUBLIC_BASE_URL": url}),
        encoding="utf-8",
    )
    print(f"Demo address: {url}")
    print("Now run `make up`. Other devices on this Wi-Fi open that address and accept the")
    print("certificate warning once (Advanced -> Proceed).")


if __name__ == "__main__":
    main()
