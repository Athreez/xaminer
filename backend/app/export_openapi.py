"""Write the API's OpenAPI spec to a file, for generating the frontend's typed client.

    uv run python -m app.export_openapi ../frontend/src/api/openapi.json

Usually run through `make api-client`.
"""

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    spec = create_app(Settings(environment="development")).openapi()
    target.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
