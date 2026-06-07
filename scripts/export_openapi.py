from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.main import create_app
from app.services.copilot_auth_service import MockGitHubDeviceClient
from app.store import InMemoryStore
from logan_workers.activities.inference import MockCopilotAnnotationGateway


def current_openapi_schema() -> dict[str, Any]:
    app = create_app(
        store=InMemoryStore(),
        copilot_auth_client=MockGitHubDeviceClient(),
        model_gateway=MockCopilotAnnotationGateway(),
    )
    return app.openapi()


def write_openapi_snapshot(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(current_openapi_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the LogAn FastAPI OpenAPI snapshot.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/openapi.snapshot.json"),
        help="Snapshot output path.",
    )
    args = parser.parse_args()
    write_openapi_snapshot(args.out)


if __name__ == "__main__":
    main()
