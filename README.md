# OpenMerge Python

Typed, server-side Python client for OpenMerge's unified integration API.

## Setup

```bash
python -m pip install openmerge
```

```python
import os
from openmerge import OpenMerge

with OpenMerge(api_key=os.environ["OPENMERGE_API_KEY"]) as client:
    integrations = client.list_integrations("ws_123")
    models = client.list_models("ws_123")
    accounts = client.list_linked_accounts("ws_123")
```

For FastAPI and other async applications, reuse one `AsyncOpenMerge` instance
per application lifespan. It uses a pooled `httpx.AsyncClient`:

```python
from openmerge import AsyncOpenMerge

async def list_accounts():
    async with AsyncOpenMerge(api_key=os.environ["OPENMERGE_API_KEY"]) as client:
        return await client.list_linked_accounts("ws_123")
```

All network methods have async equivalents, including mapping, reconnect,
sync and bulk writeback. Use `async for` with `iterate_records`. An injected
HTTP client remains caller-owned; otherwise `aclose()` releases the pool.

Releases are published by `.github/workflows/ci.yml` on version tags such as
`v0.3.0`, after CI passes, using PyPI Trusted Publishing and the `pypi` environment.

Per-connection application-to-CRM defaults are passed server-side when the link
token is minted. Developer IR policy determines whether the customer can change
the selection in the widget:

```python
link = client.create_link_token(
    "ws_123",
    "customer_456",
    mapping_overrides={"salesforce": {"Contact": {"research_bio": "Research_Bio__c"}}},
)
```

## Hosted widgets

Every token response includes a short-lived `hostedUrl`. It is the universal
fallback for server-rendered applications, native apps, desktop apps, and teams
that do not install a frontend SDK. Appearance uses validated design tokens;
arbitrary CSS and scripts never cross the widget boundary.

```python
from openmerge import MappingLinkToken, WidgetAppearance, hosted_widget_url

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

link = client.create_link_token(
    "ws_123",
    "customer_456",
    host_origin="https://app.example.com",
    appearance=appearance,
)
connect_url = link["hostedUrl"]
manager_url = hosted_widget_url(link, "manager")
sync_status_url = hosted_widget_url(link, "sync-status")

reconnect = client.create_reconnect_token(
    "ws_123",
    "linked_account_789",
    host_origin="https://app.example.com",
    appearance=appearance,
)
```

For connection-specific field mapping, mint a mapping token after schema
discovery. The specialized mapping-token response always carries both the
hosted mapping URL and the discovery job ID:

```python
mapping: MappingLinkToken = client.create_connection_mapping_token(
    "linked_account_789",
    host_origin="https://app.example.com",
    appearance=appearance,
)
mapping_url = hosted_widget_url(mapping, model="Contact")
discovery_job_id = mapping["discoveryJobId"]
```

When `mode` is omitted, `hosted_widget_url` preserves a valid mode already in
the API-provided URL and otherwise defaults to `connect`. By default, it trusts
only `https://widgets.openmerge.dev` plus HTTP(S) loopback development origins.
Self-hosted deployments must pass their exact origin explicitly:

```python
self_hosted = hosted_widget_url(
    "https://connect.customer.example/connect/token-from-openmerge",
    allowed_origins=["https://connect.customer.example"],
)
```

`host_origin` must be the exact embedding origin. Omit it for a top-level hosted
flow. Never send an OpenMerge workspace API key to a browser or WebView.

## Account lifecycle and writebacks

```python
account = client.get_linked_account("linked_account_789")
client.pause_linked_account(account["id"])
client.resume_linked_account(account["id"])
client.update_linked_account_schedule(
    account["id"],
    3600,
    reconciliation_seconds_by_model={"Contact": 86400},
)

write = client.submit_writeback(
    "Contact",
    "contact_123",
    workspace_id="ws_123",
    linked_account_id=account["id"],
    changes={"email": "new@example.com"},
    idempotency_key="customer-event-123",
)
completed = client.wait_for_writeback(write["id"], "ws_123")
```

Provider create, upsert, delete, bulk, and custom-field operations use
the same durable write journal and require an application-owned idempotency
key. Bulk requests are capped at 100 actions by the public API:

```python
created = client.create_record(
    "Contact",
    workspace_id="ws_123",
    linked_account_id=account["id"],
    changes={"email": "new@example.com"},
    idempotency_key="contact-create-123",
)
upserted = client.upsert_record(
    "Contact",
    workspace_id="ws_123",
    linked_account_id=account["id"],
    unified_id="contact_123",
    changes={"research_bio": "Updated profile"},
    idempotency_key="contact-upsert-123",
)
client.bulk_records(
    "Contact",
    workspace_id="ws_123",
    linked_account_id=account["id"],
    items=[
        {"operation": "create", "changes": {"email": "second@example.com"}},
        {"operation": "create", "changes": {"email": "third@example.com"}},
    ],
    idempotency_key="contact-bulk-123",
)
client.create_custom_field(
    "Contact",
    workspace_id="ws_123",
    linked_account_id=account["id"],
    definition={
        "name": "research_bio",
        "label": "Research bio",
        "type": "long_text",
    },
    idempotency_key="contact-field-123",
)
```

Operations still obey the selected connector/model capability contract; an
unsupported provider action is rejected by OpenMerge rather than silently
degraded. One native bulk request must be operation-homogeneous. The SDK also
rejects blank scope/record identifiers, empty write payloads, ambiguous bulk
identities, and operation-invalid bulk fields before making an HTTP request.

## Developer IR and mapping contracts

The effective Developer IR response includes the immutable `base_document`,
the current materialized `document`, mapping requirements, hashes, and
generation. Revisions are returned newest-first and can be used for audit or
rollback tooling:

```python
effective = client.get_developer_ir("ws_123", "oauth_app_123", "Contact")
revisions = client.list_developer_ir_revisions(
    "ws_123", "oauth_app_123", "Contact", limit=25
)
mapping_schema = client.get_connection_mapping(account["id"])
```

Mapping schema and job types include application/provider field metadata,
binding provenance, schema observation state, generation pins, activation
results, errors, and lifecycle timestamps.

`delete_linked_account` is destructive and starts governed credential/data
erasure; its result includes the erasure job ID and state.

API keys stay on the server. Browser applications should receive only short-lived link tokens. Writes require an application-owned idempotency key. Webhooks must be verified against the exact raw body before JSON parsing:

```python
import json
from typing import cast

from openmerge import WebhookEnvelope, verify_webhook_signature

verified = verify_webhook_signature(raw_body, signature_header, webhook_secret)
event = cast(WebhookEnvelope, json.loads(verified.payload))
```

Signature verification deliberately returns raw bytes. Parse the envelope only
after verification so whitespace or encoding changes cannot invalidate the
HMAC boundary. Typed envelopes expose `event`, complete tenant/connection
`ctx`, record `data`, and replay/cursor `breadcrumbs`.
`RecordWebhookEnvelope` models `record.created`, `record.updated`, and
`record.deleted` CDC deliveries. `DomainWebhookEnvelope` models the
control-plane telemetry outbox, whose breadcrumbs carry `entity` and
`request_id`. `WebhookEnvelope` is the union accepted by a shared handler.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy
pytest
python -m build
```

## Codex and GPT-5.6

Codex and GPT-5.6 were used to audit the API contract, design the retry/idempotency and webhook-verification boundaries, generate the initial implementation, and build the automated test matrix. Maintainers remain responsible for review, release approval, and compatibility decisions.

Licensed under AGPL-3.0-only.
