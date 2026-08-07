# OpenMerge Python

Typed, server-side Python client for OpenMerge's unified integration API.

## Setup

```bash
python -m pip install openmerge
```

```python
from openmerge import OpenMerge

with OpenMerge(api_key=os.environ["OPENMERGE_API_KEY"]) as client:
    integrations = client.list_integrations("ws_123")
    models = client.list_models("ws_123")
    accounts = client.list_linked_accounts("ws_123")
```

API keys stay on the server. Browser applications should receive only short-lived link tokens. Writes require an application-owned idempotency key. Webhooks must be verified against the exact raw body before JSON parsing:

```python
from openmerge import verify_webhook_signature

verified = verify_webhook_signature(raw_body, signature_header, webhook_secret)
```

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
