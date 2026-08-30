from __future__ import annotations

import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Dict, List, Optional, cast
from urllib.parse import quote, urlparse

import httpx

from .errors import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    ValidationError,
)
from .types import (
    ConnectionMappingJob,
    ConnectionMappingSchema,
    ConnectorIntegration,
    DeveloperIR,
    LinkedAccount,
    LinkToken,
    UnifiedModelDefinition,
    UnifiedRecord,
    UnifiedRecordPage,
    Writeback,
)

_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


class OpenMerge:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openmerge.dev",
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.25,
        client: Optional[httpx.Client] = None,
        allow_insecure_http: bool = False,
    ) -> None:
        if not api_key.startswith("om_"):
            raise ConfigurationError("api_key must be an OpenMerge workspace key")
        parsed = urlparse(base_url)
        loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and (loopback or allow_insecure_http)
        ):
            raise ConfigurationError("base_url must use HTTPS outside loopback development")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("base_url cannot contain credentials, query, or fragment")
        if not 0 <= max_retries <= 5:
            raise ConfigurationError("max_retries must be between 0 and 5")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._owned_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    def __enter__(self) -> OpenMerge:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Any = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        request_id = str(uuid.uuid4())
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-Request-ID": request_id,
            "X-OpenMerge-SDK": "python/0.2.0",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        safe = method.upper() in {"GET", "HEAD"} or idempotency_key is not None
        attempt = 0
        while True:
            try:
                response = self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    params={
                        key: value for key, value in (query or {}).items() if value is not None
                    },
                    json=body,
                    headers=headers,
                )
            except httpx.HTTPError:
                if not safe or attempt >= self._max_retries:
                    raise
                time.sleep(self._retry_base_delay * (2**attempt))
                attempt += 1
                continue
            if response.status_code in _RETRYABLE and safe and attempt < self._max_retries:
                response.close()
                time.sleep(self._retry_base_delay * (2**attempt))
                attempt += 1
                continue
            if response.is_success:
                return None if response.status_code == 204 else response.json()
            self._raise_api_error(response)

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        try:
            details = response.json()
        except ValueError:
            details = response.text
        message = f"OpenMerge API request failed with HTTP {response.status_code}"
        if isinstance(details, dict):
            detail = details.get("detail")
            if isinstance(detail, str):
                message = detail
            elif isinstance(details.get("message"), str):
                message = details["message"]
        error_type = {
            401: AuthenticationError,
            403: PermissionError,
            404: NotFoundError,
            409: ConflictError,
            429: RateLimitError,
            400: ValidationError,
            422: ValidationError,
        }.get(response.status_code, APIError)
        raise error_type(
            message,
            status_code=response.status_code,
            request_id=response.headers.get("x-request-id"),
            retryable=response.status_code in _RETRYABLE,
            details=details,
        )

    def create_link_token(
        self,
        workspace_id: str,
        end_user_origin_id: str,
        *,
        allowed_categories: Optional[Sequence[str]] = None,
        host_origin: Optional[str] = None,
        mapping_overrides: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
    ) -> LinkToken:
        value = self._request(
            "POST",
            "/link-tokens",
            body={
                "wsid": workspace_id,
                "end_user_origin_id": end_user_origin_id,
                "allowed_categories": allowed_categories,
                "host_origin": host_origin,
                "mapping_overrides": mapping_overrides,
            },
        )
        return {
            "token": value["token"],
            "expiresIn": value["expires_in"],
            "hostedUrl": value["hosted_url"],
        }

    def list_integrations(self, workspace_id: str) -> List[ConnectorIntegration]:
        value = self._request("GET", "/integrations", query={"wsid": workspace_id})
        return cast(List[ConnectorIntegration], value["integrations"])

    def list_models(self, workspace_id: Optional[str] = None) -> List[UnifiedModelDefinition]:
        value = self._request("GET", "/models", query={"wsid": workspace_id})
        return cast(List[UnifiedModelDefinition], value["models"])

    def list_linked_accounts(self, workspace_id: str) -> List[LinkedAccount]:
        value = self._request("GET", "/linked-accounts", query={"wsid": workspace_id})
        return cast(List[LinkedAccount], value["linked_accounts"])

    def trigger_sync(
        self, linked_account_id: str, models: Optional[Sequence[str]] = None
    ) -> List[Dict[str, Any]]:
        value = self._request(
            "POST",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/sync",
            body={"models": models},
        )
        return cast(List[Dict[str, Any]], value["runs"])

    def get_developer_ir(self, workspace_id: str, oauth_app_id: str, model_id: str) -> DeveloperIR:
        value = self._request(
            "GET",
            f"/developer-ir/{quote(oauth_app_id, safe='')}/{quote(model_id, safe='')}",
            query={"wsid": workspace_id},
        )
        return cast(DeveloperIR, value)

    def update_developer_ir(
        self,
        workspace_id: str,
        oauth_app_id: str,
        model_id: str,
        *,
        expected_generation: int,
        fields: Mapping[str, Mapping[str, Any]],
        removed_fields: Sequence[str] = (),
    ) -> DeveloperIR:
        value = self._request(
            "PUT",
            f"/developer-ir/{quote(oauth_app_id, safe='')}/{quote(model_id, safe='')}",
            query={"wsid": workspace_id},
            body={
                "expected_generation": expected_generation,
                "fields": {name: dict(field) for name, field in fields.items()},
                "removed_fields": list(removed_fields),
            },
        )
        return cast(DeveloperIR, value)

    def get_connection_mapping(self, linked_account_id: str) -> ConnectionMappingSchema:
        value = self._request(
            "GET",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/field-mapping",
        )
        return cast(ConnectionMappingSchema, value)

    def create_connection_mapping_token(
        self, linked_account_id: str, *, host_origin: Optional[str] = None
    ) -> LinkToken:
        value = self._request(
            "POST",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/field-mapping-token",
            body={"host_origin": host_origin},
        )
        return {
            "token": value["token"],
            "expiresIn": value["expires_in"],
            "hostedUrl": value["hosted_url"],
        }

    def activate_connection_mapping(
        self,
        linked_account_id: str,
        *,
        expected_developer_generations: Mapping[str, int],
        mappings: Mapping[str, Mapping[str, str]],
        idempotency_key: Optional[str] = None,
    ) -> ConnectionMappingJob:
        value = self._request(
            "POST",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/field-mapping",
            body={
                "expected_developer_generations": dict(expected_developer_generations),
                "mappings": {model: dict(fields) for model, fields in mappings.items()},
                "idempotency_key": idempotency_key,
            },
        )
        return cast(ConnectionMappingJob, value)

    def get_connection_mapping_job(self, job_id: str) -> ConnectionMappingJob:
        value = self._request("GET", f"/connection-mapping-jobs/{quote(job_id, safe='')}")
        return cast(ConnectionMappingJob, value)

    def list_records(
        self,
        model: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        cursor: Optional[str] = None,
        page_size: int = 100,
        include_remote_data: bool = False,
        include_deleted: bool = False,
    ) -> UnifiedRecordPage:
        value = self._request(
            "GET",
            f"/unified/{quote(model, safe='')}",
            query={
                "wsid": workspace_id,
                "linked_account_id": linked_account_id,
                "cursor": cursor,
                "page_size": page_size,
                "include_remote_data": include_remote_data,
                "include_deleted": include_deleted,
            },
        )
        return {"records": value["records"], "nextCursor": value.get("next_cursor")}

    def iterate_records(self, model: str, **params: Any) -> Iterator[UnifiedRecord]:
        cursor = params.pop("cursor", None)
        while True:
            page = self.list_records(model, cursor=cursor, **params)
            yield from page["records"]
            cursor = page["nextCursor"]
            if cursor is None:
                return

    def submit_writeback(
        self,
        model: str,
        unified_id: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        changes: Mapping[str, Any],
        idempotency_key: str,
    ) -> Writeback:
        if not 8 <= len(idempotency_key) <= 200:
            raise ConfigurationError("idempotency_key must contain 8 to 200 characters")
        if not changes:
            raise ConfigurationError("changes must not be empty")
        value = self._request(
            "POST",
            f"/unified/{quote(model, safe='')}/{quote(unified_id, safe='')}",
            body={
                "wsid": workspace_id,
                "linked_account_id": linked_account_id,
                "changes": dict(changes),
            },
            idempotency_key=idempotency_key,
        )
        return cast(Writeback, value["write"])

    def get_writeback(self, write_id: str, workspace_id: str) -> Writeback:
        value = self._request(
            "GET", f"/unified/writes/{quote(write_id, safe='')}", query={"wsid": workspace_id}
        )
        return cast(Writeback, value["write"])
