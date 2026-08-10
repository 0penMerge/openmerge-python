from .client import OpenMerge
from .errors import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    OpenMergeError,
    PermissionError,
    RateLimitError,
    ValidationError,
    WebhookVerificationError,
)
from .webhooks import VerifiedWebhook, verify_webhook_signature

__all__ = [
    "APIError",
    "AuthenticationError",
    "ConfigurationError",
    "ConflictError",
    "NotFoundError",
    "OpenMerge",
    "OpenMergeError",
    "PermissionError",
    "RateLimitError",
    "ValidationError",
    "VerifiedWebhook",
    "WebhookVerificationError",
    "verify_webhook_signature",
]

__version__ = "0.2.0"
