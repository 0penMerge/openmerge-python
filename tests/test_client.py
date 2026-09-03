import json
from typing import get_args
from unittest.mock import patch

import httpx
import pytest

from openmerge import (
    ConfigurationError,
    ConflictError,
    DomainWebhookEnvelope,
    DomainWebhookEvent,
    OpenMerge,
    OpenMergeError,
    RecordWebhookEnvelope,
    LinkedAccountReauthRequiredWebhookEnvelope,
    RecordWebhookEvent,
    RequestTimeoutError,
    WebhookEnvelope,
    WidgetAppearance,
    __version__,
    hosted_widget_url,
)


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
    assert requests[0].headers["x-openmerge-sdk"] == f"python/{__version__}"
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
    appearance: WidgetAppearance = {
        "mode": "dark",
        "colors": {
            "primary": "#f97316",
            "surfaceHover": "#18181b",
            "borderStrong": "#3f3f46",
        },
        "branding": {
            "productName": "Acme Connect",
            "logoUrl": "https://assets.example/acme.svg",
        },
    }

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
        host_origin="https://app.example",
        appearance=appearance,
        mapping_overrides={"salesforce": {"Contact": {"research_bio": "Research_Bio__c"}}},
    )
    assert captured["host_origin"] == "https://app.example"
    assert captured["appearance"] == appearance
    assert captured["mapping_overrides"] == {
        "salesforce": {"Contact": {"research_bio": "Research_Bio__c"}}
    }


def test_reconnect_token_returns_hosted_url_and_forwards_session_configuration() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "token": "r" * 32,
                "expires_in": 1800,
                "hosted_url": "https://widgets.openmerge.dev/connect/reconnect-token",
            },
        )

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    token = client.create_reconnect_token(
        "ws_1",
        "la_1",
        end_user_origin_id="customer_1",
        host_origin="chrome-extension://abcdefghijklmnop",
        appearance={"density": "compact"},
        mapping_overrides={"hubspot": {"Contact": {"bio": "research_bio"}}},
    )

    assert token["hostedUrl"].endswith("/connect/reconnect-token")
    assert captured == {
        "wsid": "ws_1",
        "linked_account_id": "la_1",
        "end_user_origin_id": "customer_1",
        "host_origin": "chrome-extension://abcdefghijklmnop",
        "appearance": {"density": "compact"},
        "mapping_overrides": {"hubspot": {"Contact": {"bio": "research_bio"}}},
    }


def test_hosted_widget_url_derives_modes_without_exposing_or_replacing_token() -> None:
    link = {
        "token": "a" * 32,
        "expiresIn": 1800,
        "hostedUrl": f"https://widgets.openmerge.dev/connect/{'a' * 32}",
    }
    assert hosted_widget_url(link, "manager") == (
        f"https://widgets.openmerge.dev/connect/{'a' * 32}?mode=manager"
    )
    assert hosted_widget_url(link, "field-mapping", "CustomContact_2") == (
        f"https://widgets.openmerge.dev/connect/{'a' * 32}?mode=field-mapping&model=CustomContact_2"
    )
    assert (
        hosted_widget_url(
            f"http://localhost:3001/connect/{'b' * 32}?mode=field-mapping", "sync-status"
        )
        == f"http://localhost:3001/connect/{'b' * 32}?mode=sync-status"
    )
    assert (
        hosted_widget_url(f"https://widgets.openmerge.dev/connect/{'c' * 32}?mode=field-mapping")
        == f"https://widgets.openmerge.dev/connect/{'c' * 32}?mode=field-mapping"
    )
    assert (
        hosted_widget_url(f"https://widgets.openmerge.dev/connect/{'d' * 32}")
        == f"https://widgets.openmerge.dev/connect/{'d' * 32}?mode=connect"
    )


def test_hosted_widget_url_requires_explicit_self_hosted_origin() -> None:
    value = f"https://connect.customer.example/connect/{'a' * 32}?mode=manager"
    with pytest.raises(ConfigurationError, match="allowed_origins"):
        hosted_widget_url(value)
    assert (
        hosted_widget_url(
            value,
            allowed_origins=["https://connect.customer.example"],
        )
        == f"https://connect.customer.example/connect/{'a' * 32}?mode=manager"
    )


def test_link_token_rejects_blank_category_scope_before_http() -> None:
    client = OpenMerge(api_key="om_test_secret", base_url="http://localhost:8000")
    with pytest.raises(ConfigurationError, match=r"allowed_categories\[1\]"):
        client.create_link_token(
            "ws_1",
            "customer_1",
            allowed_categories=["crm", "  "],
        )
    client.close()


@pytest.mark.parametrize(
    "url",
    [
        f"http://widgets.example/connect/{'a' * 32}",
        f"https://user:secret@widgets.example/connect/{'a' * 32}",
        "https://widgets.example/not-connect/not-a-token",
    ],
)
def test_hosted_widget_url_rejects_unsafe_or_malformed_urls(url: str) -> None:
    with pytest.raises(ConfigurationError):
        hosted_widget_url(url)


def test_hosted_widget_url_rejects_invalid_model() -> None:
    with pytest.raises(ConfigurationError, match="model"):
        hosted_widget_url(
            f"https://widgets.openmerge.dev/connect/{'a' * 32}",
            "field-mapping",
            "../Contact",
        )


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
                    "hosted_url": (
                        f"https://widgets.openmerge.dev/connect/{'t' * 32}?mode=field-mapping"
                    ),
                    "discovery_job_id": "map-discover-1",
                },
            )
        if request.url.path.endswith("/revisions"):
            return httpx.Response(
                200,
                json={
                    "revisions": [
                        {
                            "head_id": "developer-ir:ws_1:oa_1:Contact",
                            "wsid": "ws_1",
                            "oauth_app_id": "oa_1",
                            "model_id": "Contact",
                            "generation": 1,
                            "base_hash": "sha256:base",
                            "document_hash": "sha256:test",
                            "document": {"kind": "model", "id": "Contact", "fields": {}},
                            "requirements": {},
                            "removed_fields": [],
                            "actor_id": "user_1",
                            "created_at": 1.0,
                        }
                    ]
                },
            )
        if request.url.path.startswith("/developer-ir/"):
            payload = {
                "wsid": "ws_1",
                "oauth_app_id": "oa_1",
                "model_id": "Contact",
                "generation": 1,
                "document_hash": "sha256:test",
                "requirements": {},
                "document": {},
                "removed_fields": [],
            }
            if request.method == "GET":
                payload["base_document"] = {
                    "kind": "model",
                    "id": "Contact",
                    "fields": {},
                }
            return httpx.Response(
                200,
                json=payload,
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
        fields={
            "customer_tier": {
                "type": "enum",
                "values": ["standard", "enterprise"],
                "required": True,
                "direction": "two_way",
            },
            "research_profile": {
                "type": "array",
                "items": {"type": "string"},
                "ref": "#/models/ResearchProfile",
                "sensitivity": "pii",
            },
        },
    )
    assert developer["generation"] == 1
    token = client.create_connection_mapping_token(
        "la_1",
        host_origin="https://customer.example",
        appearance={"colors": {"borderStrong": "#3f3f46"}},
    )
    assert token["expiresIn"] == 1800
    assert token["discoveryJobId"] == "map-discover-1"
    assert hosted_widget_url(token, model="Contact") == (
        f"https://widgets.openmerge.dev/connect/{'t' * 32}?mode=field-mapping&model=Contact"
    )
    assert json.loads(requests[1].content) == {
        "host_origin": "https://customer.example",
        "appearance": {"colors": {"borderStrong": "#3f3f46"}},
    }
    job = client.activate_connection_mapping(
        "la_1",
        expected_developer_generations={"Contact": 1},
        mappings={"Contact": {"customer_tier": "Customer_Tier__c"}},
        idempotency_key="mapping-1",
    )
    assert job["state"] == "queued"
    assert requests[0].url.params["wsid"] == "ws_1"
    assert json.loads(requests[0].content)["fields"]["research_profile"] == {
        "type": "array",
        "items": {"type": "string"},
        "ref": "#/models/ResearchProfile",
        "sensitivity": "pii",
    }
    effective = client.get_developer_ir("ws_1", "oa_1", "Contact")
    assert effective["base_document"]["id"] == "Contact"
    revisions = client.list_developer_ir_revisions("ws_1", "oa_1", "Contact", limit=25)
    assert revisions[0]["base_hash"] == "sha256:base"
    assert requests[-1].url.params["wsid"] == "ws_1"
    assert requests[-1].url.params["limit"] == "25"


def test_record_action_wrappers_use_durable_idempotent_contracts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202,
            json={
                "write": {
                    "id": f"write_{len(requests)}",
                    "workflow_id": f"workflow_{len(requests)}",
                    "state": "queued",
                }
            },
        )

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    common = {
        "workspace_id": "ws_1",
        "linked_account_id": "la_1",
        "idempotency_key": "customer-command-123",
    }
    assert (
        client.create_record("Contact", changes={"email": "a@example.com"}, **common)["id"]
        == "write_1"
    )
    client.upsert_record(
        "Contact",
        unified_id="unified_1",
        changes={"email": "b@example.com"},
        **common,
    )
    client.delete_record("Contact", "unified_1", **common)
    client.bulk_records(
        "Contact",
        items=[
            {"operation": "create", "changes": {"email": "c@example.com"}},
            {"operation": "create", "changes": {"email": "d@example.com"}},
        ],
        **common,
    )
    client.create_custom_field(
        "Contact",
        definition={
            "name": "research_bio",
            "label": "Research bio",
            "type": "long_text",
        },
        **common,
    )

    assert [request.url.path for request in requests] == [
        "/unified/Contact/actions/create",
        "/unified/Contact/actions/upsert",
        "/unified/Contact/actions/delete",
        "/unified/Contact/actions/bulk",
        "/unified/Contact/actions/custom-fields",
    ]
    assert all(request.headers["idempotency-key"] == "customer-command-123" for request in requests)
    assert json.loads(requests[1].content)["unified_id"] == "unified_1"
    assert json.loads(requests[3].content)["items"][1] == {
        "operation": "create",
        "changes": {"email": "d@example.com"},
    }
    assert json.loads(requests[4].content)["definition"]["name"] == "research_bio"


def test_record_action_wrappers_reject_invalid_local_contracts() -> None:
    client = OpenMerge(api_key="om_test_secret", base_url="http://localhost:8000")
    common = {
        "workspace_id": "ws_1",
        "linked_account_id": "la_1",
        "idempotency_key": "command-123",
    }
    with pytest.raises(ConfigurationError, match="unified_id"):
        client.delete_record("Contact", "", **common)
    with pytest.raises(ConfigurationError, match="between 1 and 100"):
        client.bulk_records("Contact", items=[], **common)
    with pytest.raises(ConfigurationError, match="operation"):
        client.bulk_records("Contact", items=[{"operation": "merge"}], **common)  # type: ignore
    with pytest.raises(ConfigurationError, match="homogeneous"):
        client.bulk_records(
            "Contact",
            items=[
                {"operation": "create", "changes": {"name": "A"}},
                {"operation": "delete", "remote_id": "remote_1"},
            ],
            **common,
        )
    with pytest.raises(ConfigurationError, match="changes must not be empty"):
        client.bulk_records("Contact", items=[{"operation": "create"}], **common)
    with pytest.raises(ConfigurationError, match="requires one record ID"):
        client.bulk_records(
            "Contact",
            items=[{"operation": "update", "changes": {"name": "A"}}],
            **common,
        )
    with pytest.raises(ConfigurationError, match="must not include changes"):
        client.bulk_records(
            "Contact",
            items=[
                {
                    "operation": "delete",
                    "remote_id": "remote_1",
                    "changes": {"name": "A"},
                }
            ],
            **common,
        )
    with pytest.raises(ConfigurationError, match="only one ID"):
        client.bulk_records(
            "Contact",
            items=[
                {
                    "operation": "upsert",
                    "unified_id": "unified_1",
                    "remote_id": "remote_1",
                    "changes": {"name": "A"},
                }
            ],
            **common,
        )
    with pytest.raises(ConfigurationError, match="changes must not be empty"):
        client.create_record("Contact", changes={}, **common)
    with pytest.raises(ConfigurationError, match="changes must not be empty"):
        client.upsert_record("Contact", changes={}, **common)
    with pytest.raises(ConfigurationError, match="definition"):
        client.create_custom_field("Contact", definition={}, **common)  # type: ignore
    with pytest.raises(ConfigurationError, match="definition.name"):
        client.create_custom_field("Contact", definition={"name": "  "}, **common)
    with pytest.raises(ConfigurationError, match="workspace_id"):
        client.create_record(
            "Contact",
            workspace_id="  ",
            linked_account_id="la_1",
            changes={"name": "A"},
            idempotency_key="command-123",
        )
    with pytest.raises(ConfigurationError, match="model"):
        client.create_record("Contact-name", changes={"name": "A"}, **common)
    with pytest.raises(ConfigurationError, match="linked_account_id"):
        client.create_record(
            "Contact",
            workspace_id="ws_1",
            linked_account_id="  ",
            changes={"name": "A"},
            idempotency_key="command-123",
        )
    with pytest.raises(ConfigurationError, match="idempotency_key"):
        client.create_record(
            "Contact",
            workspace_id="ws_1",
            linked_account_id="la_1",
            changes={"name": "A"},
            idempotency_key="short",
        )
    client.close()


def test_webhook_envelope_union_tracks_record_and_domain_wire_families() -> None:
    assert set(get_args(WebhookEnvelope)) == {
        RecordWebhookEnvelope,
        DomainWebhookEnvelope,
        LinkedAccountReauthRequiredWebhookEnvelope,
    }
    assert set(get_args(RecordWebhookEvent)).isdisjoint(get_args(DomainWebhookEvent))


def test_linked_account_lifecycle_and_schedule_contracts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "la_1", "status": "healthy"})
        if request.url.path.endswith("/pause"):
            return httpx.Response(200, json={"id": "la_1", "status": "paused", "cancelled_runs": 2})
        if request.url.path.endswith("/resume"):
            return httpx.Response(
                200,
                json={
                    "id": "la_1",
                    "status": "healthy",
                    "runs": [{"id": "run_1", "workflow_id": "wf_1", "state": "queued"}],
                },
            )
        if request.method == "PUT":
            return httpx.Response(
                200,
                json={
                    "id": "la_1",
                    "cadence_seconds": 3600,
                    "scheduled_models": ["Contact"],
                    "reconciliation_seconds_by_model": {"Contact": 86400},
                },
            )
        return httpx.Response(
            200,
            json={
                "deleted": True,
                "cancelled_runs": 1,
                "erasure_job_id": "erase:ws_1:la_1",
                "erasure_state": "pending",
            },
        )

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.get_linked_account("la_1")["status"] == "healthy"
    assert client.pause_linked_account("la_1")["cancelled_runs"] == 2
    assert client.resume_linked_account("la_1")["runs"][0]["id"] == "run_1"
    schedule = client.update_linked_account_schedule(
        "la_1", 3600, reconciliation_seconds_by_model={"Contact": 86400}
    )
    assert schedule["reconciliation_seconds_by_model"] == {"Contact": 86400}
    assert json.loads(requests[3].content) == {
        "cadence_seconds": 3600,
        "reconciliation_seconds_by_model": {"Contact": 86400},
    }
    assert client.delete_linked_account("la_1")["erasure_state"] == "pending"
    assert [request.method for request in requests] == ["GET", "POST", "POST", "PUT", "DELETE"]


def test_record_iteration_preserves_read_flags_and_rejects_repeated_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        cursor = request.url.params.get("cursor")
        if cursor == "repeat":
            return httpx.Response(200, json={"records": [], "next_cursor": "repeat"})
        if cursor == "page_2":
            return httpx.Response(
                200,
                json={
                    "records": [{"unified_id": "u_2", "data": {}}],
                    "next_cursor": None,
                },
            )
        return httpx.Response(
            200,
            json={
                "records": [
                    {
                        "unified_id": "u_1",
                        "data": {},
                        "deleted_at": 1_725_000_000.0,
                        "deletion_source": "full_inventory",
                        "updated_at": 1_725_000_001.0,
                    }
                ],
                "next_cursor": "page_2",
            },
        )

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    records = list(
        client.iterate_records(
            "Contact",
            workspace_id="ws_1",
            linked_account_id="la_1",
            include_remote_data=True,
            include_deleted=True,
        )
    )
    assert [record["unified_id"] for record in records] == ["u_1", "u_2"]
    assert records[0]["deletion_source"] == "full_inventory"
    assert records[0]["updated_at"] == 1_725_000_001.0
    assert "provider" not in records[0]
    assert requests[0].url.params["include_remote_data"] == "true"
    assert requests[0].url.params["include_deleted"] == "true"
    assert requests[1].url.params["cursor"] == "page_2"

    with pytest.raises(OpenMergeError, match="recurring cursor"):
        list(
            client.iterate_records(
                "Contact",
                workspace_id="ws_1",
                linked_account_id="la_1",
                cursor="repeat",
            )
        )


def test_wait_for_writeback_uses_terminal_state_and_monotonic_deadline() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        state = "running" if attempts == 1 else "completed"
        return httpx.Response(200, json={"write": {"id": "w_1", "state": state}})

    client = OpenMerge(
        api_key="om_test_secret",
        base_url="http://localhost:8000",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.wait_for_writeback("w_1", "ws_1", interval_seconds=0.01, timeout_seconds=1)
    assert result["state"] == "completed"
    assert attempts == 2

    attempts = 0
    with (
        patch("openmerge.client.time.monotonic", side_effect=[100.0, 101.1]),
        pytest.raises(RequestTimeoutError) as raised,
    ):
        client.wait_for_writeback("w_2", "ws_1", interval_seconds=0.01, timeout_seconds=1)
    assert raised.value.timeout_seconds == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"interval_seconds": 0}, "interval_seconds"),
        ({"timeout_seconds": float("inf")}, "timeout_seconds"),
        ({"terminal_states": ()}, "terminal_states"),
    ],
)
def test_wait_for_writeback_rejects_invalid_polling_configuration(
    kwargs: dict, message: str
) -> None:
    client = OpenMerge(api_key="om_test_secret", base_url="http://localhost:8000")
    with pytest.raises(ConfigurationError, match=message):
        client.wait_for_writeback("w_1", "ws_1", **kwargs)
    client.close()
