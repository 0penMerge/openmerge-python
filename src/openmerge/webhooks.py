from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional, Union

from .errors import WebhookVerificationError


@dataclass(frozen=True)
class VerifiedWebhook:
    timestamp: int
    payload: bytes


def verify_webhook_signature(
    payload: Union[str, bytes],
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: int = 300,
    now: Optional[float] = None,
) -> VerifiedWebhook:
    if not secret.startswith("whsec_") or len(secret) <= len("whsec_"):
        raise WebhookVerificationError("invalid_secret", "Webhook secret must start with whsec_")
    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be non-negative")

    parts = [part.strip() for part in signature_header.split(",")]
    timestamp_values = [part[2:] for part in parts if part.startswith("t=")]
    signatures = [part[3:] for part in parts if part.startswith("v1=")]
    try:
        timestamp = int(timestamp_values[0])
    except (IndexError, ValueError):
        raise WebhookVerificationError(
            "invalid_header", "Signature header has no valid timestamp"
        ) from None
    if timestamp <= 0 or not signatures:
        raise WebhookVerificationError("invalid_header", "Signature header has no v1 signature")

    current = time.time() if now is None else now
    if abs(int(current) - timestamp) > tolerance_seconds:
        raise WebhookVerificationError(
            "timestamp_outside_tolerance", "Webhook timestamp is outside the allowed tolerance"
        )

    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    expected = hmac.new(
        secret.encode("utf-8"), str(timestamp).encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    if not any(
        len(value) == 64 and hmac.compare_digest(value.lower(), expected) for value in signatures
    ):
        raise WebhookVerificationError("signature_mismatch", "Webhook signature did not match")
    return VerifiedWebhook(timestamp=timestamp, payload=raw)
