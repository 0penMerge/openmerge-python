from __future__ import annotations

from typing import Any, Optional


class OpenMergeError(Exception):
    """Base OpenMerge SDK error."""


class ConfigurationError(OpenMergeError):
    pass


class RequestTimeoutError(OpenMergeError, TimeoutError):
    def __init__(self, message: str, *, timeout_seconds: float) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


class APIError(OpenMergeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        request_id: Optional[str] = None,
        retryable: bool = False,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.retryable = retryable
        self.details = details


class AuthenticationError(APIError):
    pass


class PermissionError(APIError):
    pass


class NotFoundError(APIError):
    pass


class ConflictError(APIError):
    pass


class RateLimitError(APIError):
    pass


class ValidationError(APIError):
    pass


class WebhookVerificationError(OpenMergeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
