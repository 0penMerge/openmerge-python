import json

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
                json={
                    "integrations": [
                        {
                            "provider": "hubspot",
                            "descriptor": {"id": "hubspot", "name": "HubSpot"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"models": []})

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


def test_link_token_carries_application_mapping_overrides() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "token": "t" * 32,
                "expires_in": 1800,
                "hosted_url": "https://connect.openmerge.dev/x",
            },
        )

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.create_link_token(
        "ws_1",
        "customer_1",
        mapping_overrides={"salesforce": {"Contact": {"research_bio": "Research_Bio__c"}}},
    )
    assert captured["mapping_overrides"] == {
        "salesforce": {"Contact": {"research_bio": "Research_Bio__c"}}
    }


def test_developer_ir_and_connection_mapping_contracts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/field-mapping-token"):
            return httpx.Response(
                200,
                json={
                    "token": "t" * 32,
                    "expires_in": 1800,
                    "hosted_url": "https://connect.openmerge.dev/x",
                },
            )
        if request.url.path.startswith("/developer-ir/"):
            return httpx.Response(
                200,
                json={
                    "wsid": "ws_1",
                    "oauth_app_id": "oa_1",
                    "model_id": "Contact",
                    "generation": 1,
                    "document_hash": "sha256:test",
                    "requirements": {},
                    "document": {},
                    "removed_fields": [],
                },
            )
        return httpx.Response(200, json={"id": "map_1", "action": "activate", "state": "queued"})

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    developer = client.update_developer_ir(
        "ws_1",
        "oa_1",
        "Contact",
        expected_generation=0,
        fields={"customer_tier": {"type": "string", "required": True}},
    )
    assert developer["generation"] == 1
    token = client.create_connection_mapping_token("la_1", host_origin="https://customer.example")
    assert token["expiresIn"] == 1800
    job = client.activate_connection_mapping(
        "la_1",
        expected_developer_generations={"Contact": 1},
        mappings={"Contact": {"customer_tier": "Customer_Tier__c"}},
        idempotency_key="mapping-1",
    )
    assert job["state"] == "queued"
    assert requests[0].url.params["wsid"] == "ws_1"
