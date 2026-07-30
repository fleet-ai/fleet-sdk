"""The SQLite query path must not parse a non-QueryResponse body as JSON.

``_query_http`` used to do a bare ``response.json()``, so anything that wasn't
200-with-JSON surfaced as an opaque ``JSONDecodeError: Expecting value: line 1
column 1 (char 0)`` (non-JSON body) or a pydantic ``ValidationError`` (a
``{"detail": ...}`` error body) -- carrying no status code, URL or body text.

On 2026-07-30 that cost a full grading session: a BLOB column made an env runner
answer ``500 Internal Server Error`` as text/plain, the char-0 JSONDecodeError
reached the generated multi-app verifier, and its "app route is dead" heuristic
failed the run ENVIRONMENT_NOT_READY -- discarding ~90 minutes of rollout and
pointing the investigation at the wrong layer.
"""

import json

import pytest

from fleet.exceptions import FleetEnvironmentError
from fleet.instance.models import (
    Resource as ResourceModel,
    ResourceMode,
    ResourceType,
)
from fleet.resources.sqlite import SQLiteResource

# The literal 21-byte text/plain body Starlette returns for an unhandled
# exception, and the one that actually broke grading.
STARLETTE_500_BODY = "Internal Server Error"
NGINX_502_BODY = (
    "<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n"
    "<body>\r\n<center><h1>502 Bad Gateway</h1></center>\r\n</body>\r\n</html>\r\n"
)


class FakeResponse:
    def __init__(self, status_code, text, content_type="application/json"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}

    def json(self):
        return json.loads(self.text)


class FakeClient:
    """Stands in for SyncWrapper; records the call and returns a canned response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.response


def _resource(client):
    return SQLiteResource(
        ResourceModel(name="current", type=ResourceType.db, mode=ResourceMode.rw),
        client,
    )


def test_text_plain_500_raises_descriptive_error_not_jsondecodeerror():
    """The exact production failure."""
    client = FakeClient(
        FakeResponse(500, STARLETTE_500_BODY, content_type="text/plain; charset=utf-8")
    )

    with pytest.raises(FleetEnvironmentError) as excinfo:
        _resource(client).query("SELECT * FROM vendor_contract_documents WHERE id = 12")

    message = str(excinfo.value)
    assert "status_code=500" in message
    assert STARLETTE_500_BODY in message
    assert "current" in message
    assert "text/plain" in message
    # The old failure mode must be gone.
    assert "line 1 column 1 (char 0)" not in message


def test_gateway_body_is_preserved_for_unavailability_classification():
    """Callers classify "unreachable" on the reason phrase, so keep the body.

    orchestrator/tasks/activities/verifier.py matches phrases like "Bad Gateway"
    to tell an unreachable app apart from a real task failure. Including the body
    snippet keeps that working through the new exception.
    """
    client = FakeClient(FakeResponse(502, NGINX_502_BODY, content_type="text/html"))

    with pytest.raises(FleetEnvironmentError) as excinfo:
        _resource(client).query("SELECT 1")

    assert "Bad Gateway" in str(excinfo.value)
    assert "status_code=502" in str(excinfo.value)


@pytest.mark.parametrize(
    "status,body",
    [
        (404, '{"detail": "Database file not found: /alloc/data/current.sqlite"}'),
        (401, '{"detail": "unauthorized: runner SQL write requires X-Runner-Token"}'),
    ],
)
def test_json_error_bodies_raise_descriptive_error_not_validationerror(status, body):
    """`{"detail": ...}` used to blow up as a pydantic ValidationError."""
    client = FakeClient(FakeResponse(status, body))

    with pytest.raises(FleetEnvironmentError) as excinfo:
        _resource(client).query("SELECT 1")

    assert f"status_code={status}" in str(excinfo.value)
    assert "detail" in str(excinfo.value)


def test_empty_200_body_raises_descriptive_error():
    client = FakeClient(FakeResponse(200, ""))

    with pytest.raises(FleetEnvironmentError) as excinfo:
        _resource(client).query("SELECT 1")

    assert "status_code=200" in str(excinfo.value)
    assert "empty" in str(excinfo.value)


def test_successful_query_is_untouched():
    """No working call may change behaviour: 200-with-JSON still parses."""
    payload = {
        "success": True,
        "columns": ["id", "file_name"],
        "rows": [[12, "signed.pdf"]],
        "message": "Query executed successfully",
    }
    client = FakeClient(FakeResponse(200, json.dumps(payload)))

    result = _resource(client).query("SELECT id, file_name FROM t")

    assert result.success is True
    assert result.rows == [[12, "signed.pdf"]]
    assert client.calls[0][0] == "POST"
    assert client.calls[0][1] == "/resources/sqlite/current/query"


def test_sql_error_response_still_returned_as_data_not_raised():
    """A failed *query* (200 + success=False) is data, not a transport error."""
    payload = {
        "success": False,
        "error": "no such table: nope",
        "message": "Query execution failed",
    }
    client = FakeClient(FakeResponse(200, json.dumps(payload)))

    result = _resource(client).query("SELECT * FROM nope")

    assert result.success is False
    assert "no such table" in result.error


def test_write_path_shares_the_guard():
    """`exec()` goes through the same helper."""
    client = FakeClient(
        FakeResponse(500, STARLETTE_500_BODY, content_type="text/plain")
    )

    with pytest.raises(FleetEnvironmentError):
        _resource(client).exec("UPDATE t SET x = 1")
