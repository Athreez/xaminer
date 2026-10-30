"""deploy/.env for a throwaway stack (CI): .env.example with every change-me value replaced by a
fresh random one. Never use it for real data: the secrets exist only for this run."""

import re
import secrets
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
text = (DEPLOY / ".env.example").read_text(encoding="utf-8")
text = re.sub(
    r"^([A-Z_]+)=change-me\S*$",
    lambda m: f"{m.group(1)}={secrets.token_urlsafe(32)}",
    text,
    flags=re.MULTILINE,
)
(DEPLOY / ".env").write_text(text, encoding="utf-8")
print("deploy/.env written with random secrets")
