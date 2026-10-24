import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import AppError
from app.main import API_PREFIX, create_app


class Item(BaseModel):
    name: str
    count: int


def build_app() -> FastAPI:
    app = create_app(Settings(environment="test"))

    @app.get(f"{API_PREFIX}/_test/app-error")
    async def app_error() -> None:
        raise AppError("ATTEMPT_NOT_ACTIVE", "This attempt has ended.", status_code=409)

    @app.get(f"{API_PREFIX}/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.post(f"{API_PREFIX}/_test/items")
    async def items(item: Item) -> Item:
        return item

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def test_health(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_generated_and_returned(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/health")
    assert len(response.headers["x-request-id"]) == 32


def test_request_id_passed_through(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


def test_unsafe_request_id_replaced(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["x-request-id"] != "bad id\nwith newline"


def test_not_found_uses_error_format(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/nope", headers={"X-Request-ID": "r1"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found", "request_id": "r1"}
    }


def test_app_error(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/_test/app-error")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ATTEMPT_NOT_ACTIVE"


def test_validation_error_lists_fields(client: TestClient) -> None:
    response = client.post(f"{API_PREFIX}/_test/items", json={"name": "x", "count": "many"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert error["details"][0]["field"] == "body.count"


def test_unhandled_error_hides_details(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/_test/boom", headers={"X-Request-ID": "r2"})
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Something went wrong on our side.",
            "request_id": "r2",
        }
    }
    assert "secret" not in response.text
    assert response.headers["x-request-id"] == "r2"


def test_access_log_is_json_with_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    client = TestClient(build_app())  # built inside the test so the log handler writes to capsys
    client.get(f"{API_PREFIX}/health?token=should-not-be-logged", headers={"X-Request-ID": "r3"})
    ours = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{") and '"logger": "xaminer.' in line
    ]
    assert ours[-1]["request_id"] == "r3"
    assert ours[-1]["path"] == f"{API_PREFIX}/health"
    assert ours[-1]["status"] == 200
    assert "should-not-be-logged" not in json.dumps(ours)


def test_docs_hidden_in_production() -> None:
    prod = TestClient(create_app(Settings(environment="production")))
    assert prod.get(f"{API_PREFIX}/docs").status_code == 404
    assert prod.get(f"{API_PREFIX}/openapi.json").status_code == 200


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    # create_app replaces root handlers; make sure capsys sees the current stderr each test.
    logging.getLogger().handlers.clear()
