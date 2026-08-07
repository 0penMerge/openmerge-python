import httpx
import pytest

from openmerge import ConflictError, OpenMerge


def test_catalog_and_workspace_headers() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations":
            return httpx.Response(
                200,
                json=[{"provider": "hubspot", "descriptor": {"id": "hubspot", "name": "HubSpot"}}],
            )
        return httpx.Response(200, json=[])

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.list_integrations("ws_1")[0]["provider"] == "hubspot"
    assert client.list_models("ws_1") == []
    assert requests[0].headers["authorization"] == "Bearer om_test_secret"
    assert requests[0].url.params["wsid"] == "ws_1"


def test_idempotent_write_retries_and_preserves_key() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.headers["idempotency-key"] == "customer-event-123"
        if attempts == 1:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(
            202, json={"write": {"id": "w_1", "workflow_id": "wf_1", "state": "queued"}}
        )

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        retry_base_delay=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    write = client.submit_writeback(
        "Contact",
        "u_1",
        workspace_id="ws_1",
        linked_account_id="la_1",
        changes={"email": "new@example.com"},
        idempotency_key="customer-event-123",
    )
    assert write["id"] == "w_1"
    assert attempts == 2


def test_conflict_is_typed() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "key reused"})

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ConflictError):
        client.submit_writeback(
            "Contact",
            "u_1",
            workspace_id="ws_1",
            linked_account_id="la_1",
            changes={"email": "new@example.com"},
            idempotency_key="customer-event-123",
        )
