import hashlib
import hmac

import pytest

from openmerge import WebhookVerificationError, verify_webhook_signature


def test_verifies_raw_body_and_rotation_signatures() -> None:
    payload = b'{"event":"record.updated"}'
    timestamp = 1_750_000_000
    secret = "whsec_test"
    signature = hmac.new(
        secret.encode(), str(timestamp).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    verified = verify_webhook_signature(
        payload,
        f"t={timestamp},v1={'0' * 64},v1={signature}",
        secret,
        now=float(timestamp),
    )
    assert verified.payload == payload


def test_rejects_stale_or_modified_payloads() -> None:
    payload = b"{}"
    timestamp = 1_750_000_000
    secret = "whsec_test"
    signature = hmac.new(
        secret.encode(), str(timestamp).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    with pytest.raises(WebhookVerificationError):
        verify_webhook_signature(
            payload, f"t={timestamp},v1={signature}", secret, now=timestamp + 301
        )
    with pytest.raises(WebhookVerificationError):
        verify_webhook_signature(
            payload + b" ", f"t={timestamp},v1={signature}", secret, now=timestamp
        )
