from __future__ import annotations

import math
import re
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Dict, List, Optional, Union, cast
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import httpx

from .errors import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    OpenMergeError,
    PermissionError,
    RateLimitError,
    RequestTimeoutError,
    ValidationError,
)
from .types import (
    AccountDeletion,
    AccountSchedule,
    AccountTransition,
    BulkRecordActionItem,
    ConnectionMappingJob,
    ConnectionMappingSchema,
    ConnectorIntegration,
    CustomFieldDefinition,
    DeveloperIR,
    DeveloperIRField,
    DeveloperIRRevision,
    LinkedAccount,
    LinkToken,
    MappingLinkToken,
    SyncRun,
    UnifiedModelDefinition,
    UnifiedRecord,
    UnifiedRecordPage,
    WidgetAppearance,
    WidgetMode,
    Writeback,
)

_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}
_SDK_VERSION = "0.3.0"
_LINK_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,512}$")
_MODEL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_WIDGET_MODES = frozenset({"connect", "manager", "field-mapping", "sync-status"})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _validate_idempotency_key(idempotency_key: str) -> None:
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 200:
        raise ConfigurationError("idempotency_key must contain 8 to 200 characters")


def _require_nonblank(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must not be blank")
    return value


def _require_model(model: str) -> str:
    _require_nonblank("model", model)
    if not _MODEL_ID.fullmatch(model):
        raise ConfigurationError("model must be a valid OpenMerge model identifier")
    return model


def _require_nonblank_values(name: str, values: Sequence[str]) -> None:
    for index, value in enumerate(values):
        _require_nonblank(f"{name}[{index}]", value)


def _serialize_bulk_items(
    items: Sequence[BulkRecordActionItem],
) -> List[Dict[str, Any]]:
    if not 1 <= len(items) <= 100:
        raise ConfigurationError("items must contain between 1 and 100 actions")
    allowed = {"create", "update", "upsert", "delete"}
    operations: set[str] = set()
    serialized: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ConfigurationError(f"bulk item {index} must be an object")
        operation = item.get("operation")
        if operation not in allowed:
            raise ConfigurationError(f"bulk item {index} operation is not supported")
        operations.add(operation)
        unified_id = item.get("unified_id")
        remote_id = item.get("remote_id")
        if unified_id is not None:
            _require_nonblank(f"bulk item {index} unified_id", unified_id)
        if remote_id is not None:
            _require_nonblank(f"bulk item {index} remote_id", remote_id)
        if unified_id is not None and remote_id is not None:
            raise ConfigurationError(f"bulk item {index} must identify a record by only one ID")
        changes = item.get("changes", {})
        if not isinstance(changes, Mapping):
            raise ConfigurationError(f"bulk item {index} changes must be an object")
        if operation == "create" and (unified_id is not None or remote_id is not None):
            raise ConfigurationError(f"bulk create item {index} must not include an ID")
        if operation in {"update", "delete"} and unified_id is None and remote_id is None:
            raise ConfigurationError(f"bulk {operation} item {index} requires one record ID")
        if operation == "delete" and changes:
            raise ConfigurationError(f"bulk delete item {index} must not include changes")
        if operation != "delete" and not changes:
            raise ConfigurationError(f"bulk {operation} item {index} changes must not be empty")
        serialized.append(dict(item))
    if len(operations) != 1:
        raise ConfigurationError("bulk actions must use one homogeneous operation")
    return serialized


def _origin(value: str, *, name: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ConfigurationError(f"{name} must be an absolute HTTP(S) origin")
    try:
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError(f"{name} contains an invalid port") from error
    loopback = parsed.hostname in _LOOPBACK_HOSTS
    if parsed.scheme != "https" and not loopback:
        raise ConfigurationError(f"{name} must use HTTPS outside loopback development")
    default_port = (parsed.scheme == "https" and port in {None, 443}) or (
        parsed.scheme == "http" and port in {None, 80}
    )
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}{'' if default_port else f':{port}'}"


def _map_link_token(value: Mapping[str, Any]) -> LinkToken:
    return {
        "token": cast(str, value["token"]),
        "expiresIn": cast(int, value["expires_in"]),
        "hostedUrl": cast(str, value["hosted_url"]),
    }


def _map_mapping_link_token(value: Mapping[str, Any]) -> MappingLinkToken:
    token = _map_link_token(value)
    return {
        **token,
        "discoveryJobId": cast(str, value["discovery_job_id"]),
    }


def hosted_widget_url(
    link_or_url: Union[LinkToken, str],
    mode: Optional[WidgetMode] = None,
    model: Optional[str] = None,
    *,
    allowed_origins: Optional[Sequence[str]] = None,
) -> str:
    """Derive a trusted hosted-widget URL while retaining its scoped token."""
    value = link_or_url if isinstance(link_or_url, str) else link_or_url.get("hostedUrl")
    if not isinstance(value, str):
        raise ConfigurationError("link_or_url must contain a hostedUrl")
    parsed = urlparse(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ConfigurationError("hosted widget URL must not contain credentials or a fragment")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ConfigurationError("hosted widget URL contains an invalid port") from error
    actual_origin = _origin(
        urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")),
        name="hosted widget origin",
    )
    trusted_origins = {"https://widgets.openmerge.dev"}
    if allowed_origins is not None:
        trusted_origins.update(
            _origin(candidate, name="allowed_origins entry") for candidate in allowed_origins
        )
    loopback = parsed.hostname in _LOOPBACK_HOSTS
    if not loopback and actual_origin not in trusted_origins:
        raise ConfigurationError(
            "hosted widget origin is not trusted; pass allowed_origins for self-hosting"
        )
    path_parts = parsed.path.rstrip("/").split("/")
    if len(path_parts) != 3 or path_parts[0] != "" or path_parts[1] != "connect":
        raise ConfigurationError("hosted widget URL must have the /connect/{token} form")
    token = path_parts[2]
    if not _LINK_TOKEN.fullmatch(token):
        raise ConfigurationError("hosted widget URL contains an invalid link token")
    existing = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(existing.get(key, ())) != 1 for key in ("mode", "model") if key in existing):
        raise ConfigurationError("hosted widget URL has an ambiguous mode or model")
    existing_mode = existing.get("mode", [None])[0]
    if existing_mode is not None and existing_mode not in _WIDGET_MODES:
        raise ConfigurationError("hosted widget URL contains an unsupported mode")
    selected_mode = mode or cast(Optional[WidgetMode], existing_mode) or "connect"
    if selected_mode not in _WIDGET_MODES:
        raise ConfigurationError("mode is not a supported OpenMerge widget mode")
    existing_model = existing.get("model", [None])[0]
    if existing_model is not None:
        _require_model(existing_model)
    selected_model = model if model is not None else existing_model if mode is None else None
    if selected_model is not None:
        _require_model(selected_model)
    query: Dict[str, str] = {"mode": selected_mode}
    if selected_model is not None:
        query["model"] = selected_model
    return urlunparse((parsed.scheme, parsed.netloc, f"/connect/{token}", "", urlencode(query), ""))


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
            "X-OpenMerge-SDK": f"python/{_SDK_VERSION}",
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
        appearance: Optional[WidgetAppearance] = None,
        mapping_overrides: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
    ) -> LinkToken:
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("end_user_origin_id", end_user_origin_id)
        if allowed_categories is not None:
            _require_nonblank_values("allowed_categories", allowed_categories)
        value = self._request(
            "POST",
            "/link-tokens",
            body={
                "wsid": workspace_id,
                "end_user_origin_id": end_user_origin_id,
                "allowed_categories": allowed_categories,
                "host_origin": host_origin,
                "appearance": appearance,
                "mapping_overrides": mapping_overrides,
            },
        )
        return _map_link_token(value)

    def create_reconnect_token(
        self,
        workspace_id: str,
        linked_account_id: str,
        *,
        end_user_origin_id: Optional[str] = None,
        host_origin: Optional[str] = None,
        appearance: Optional[WidgetAppearance] = None,
        mapping_overrides: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
    ) -> LinkToken:
        """Mint a hosted reconnect session pinned to one linked account."""
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("linked_account_id", linked_account_id)
        if end_user_origin_id is not None:
            _require_nonblank("end_user_origin_id", end_user_origin_id)
        value = self._request(
            "POST",
            "/link-tokens",
            body={
                "wsid": workspace_id,
                "linked_account_id": linked_account_id,
                "end_user_origin_id": end_user_origin_id,
                "host_origin": host_origin,
                "appearance": appearance,
                "mapping_overrides": mapping_overrides,
            },
        )
        return _map_link_token(value)

    def list_integrations(self, workspace_id: str) -> List[ConnectorIntegration]:
        _require_nonblank("workspace_id", workspace_id)
        value = self._request("GET", "/integrations", query={"wsid": workspace_id})
        return cast(List[ConnectorIntegration], value["integrations"])

    def list_models(self, workspace_id: Optional[str] = None) -> List[UnifiedModelDefinition]:
        if workspace_id is not None:
            _require_nonblank("workspace_id", workspace_id)
        value = self._request("GET", "/models", query={"wsid": workspace_id})
        return cast(List[UnifiedModelDefinition], value["models"])

    def list_linked_accounts(self, workspace_id: str) -> List[LinkedAccount]:
        _require_nonblank("workspace_id", workspace_id)
        value = self._request("GET", "/linked-accounts", query={"wsid": workspace_id})
        return cast(List[LinkedAccount], value["linked_accounts"])

    def get_linked_account(self, linked_account_id: str) -> LinkedAccount:
        _require_nonblank("linked_account_id", linked_account_id)
        value = self._request("GET", f"/linked-accounts/{quote(linked_account_id, safe='')}")
        return cast(LinkedAccount, value)

    def pause_linked_account(self, linked_account_id: str) -> AccountTransition:
        _require_nonblank("linked_account_id", linked_account_id)
        value = self._request("POST", f"/linked-accounts/{quote(linked_account_id, safe='')}/pause")
        return cast(AccountTransition, value)

    def resume_linked_account(self, linked_account_id: str) -> AccountTransition:
        _require_nonblank("linked_account_id", linked_account_id)
        value = self._request(
            "POST", f"/linked-accounts/{quote(linked_account_id, safe='')}/resume"
        )
        return cast(AccountTransition, value)

    def update_linked_account_schedule(
        self,
        linked_account_id: str,
        cadence_seconds: int,
        *,
        reconciliation_seconds_by_model: Optional[Mapping[str, int]] = None,
    ) -> AccountSchedule:
        _require_nonblank("linked_account_id", linked_account_id)
        if reconciliation_seconds_by_model is not None:
            for model in reconciliation_seconds_by_model:
                _require_model(model)
        value = self._request(
            "PUT",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/schedule",
            body={
                "cadence_seconds": cadence_seconds,
                "reconciliation_seconds_by_model": (
                    dict(reconciliation_seconds_by_model)
                    if reconciliation_seconds_by_model is not None
                    else None
                ),
            },
        )
        return cast(AccountSchedule, value)

    def delete_linked_account(self, linked_account_id: str) -> AccountDeletion:
        _require_nonblank("linked_account_id", linked_account_id)
        value = self._request("DELETE", f"/linked-accounts/{quote(linked_account_id, safe='')}")
        return cast(AccountDeletion, value)

    def trigger_sync(
        self, linked_account_id: str, models: Optional[Sequence[str]] = None
    ) -> List[SyncRun]:
        _require_nonblank("linked_account_id", linked_account_id)
        if models is not None:
            for model in models:
                _require_model(model)
        value = self._request(
            "POST",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/sync",
            body={"models": models},
        )
        return cast(List[SyncRun], value["runs"])

    def get_developer_ir(self, workspace_id: str, oauth_app_id: str, model_id: str) -> DeveloperIR:
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("oauth_app_id", oauth_app_id)
        _require_model(model_id)
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
        fields: Mapping[str, DeveloperIRField],
        removed_fields: Sequence[str] = (),
    ) -> DeveloperIR:
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("oauth_app_id", oauth_app_id)
        _require_model(model_id)
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

    def list_developer_ir_revisions(
        self,
        workspace_id: str,
        oauth_app_id: str,
        model_id: str,
        *,
        limit: int = 50,
    ) -> List[DeveloperIRRevision]:
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("oauth_app_id", oauth_app_id)
        _require_model(model_id)
        if not 1 <= limit <= 100:
            raise ConfigurationError("limit must be between 1 and 100")
        value = self._request(
            "GET",
            f"/developer-ir/{quote(oauth_app_id, safe='')}/{quote(model_id, safe='')}/revisions",
            query={"wsid": workspace_id, "limit": limit},
        )
        return cast(List[DeveloperIRRevision], value["revisions"])

    def get_connection_mapping(self, linked_account_id: str) -> ConnectionMappingSchema:
        _require_nonblank("linked_account_id", linked_account_id)
        value = self._request(
            "GET",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/field-mapping",
        )
        return cast(ConnectionMappingSchema, value)

    def create_connection_mapping_token(
        self,
        linked_account_id: str,
        *,
        host_origin: Optional[str] = None,
        appearance: Optional[WidgetAppearance] = None,
    ) -> MappingLinkToken:
        _require_nonblank("linked_account_id", linked_account_id)
        value = self._request(
            "POST",
            f"/linked-accounts/{quote(linked_account_id, safe='')}/field-mapping-token",
            body={"host_origin": host_origin, "appearance": appearance},
        )
        return _map_mapping_link_token(value)

    def activate_connection_mapping(
        self,
        linked_account_id: str,
        *,
        expected_developer_generations: Mapping[str, int],
        mappings: Mapping[str, Mapping[str, str]],
        idempotency_key: Optional[str] = None,
    ) -> ConnectionMappingJob:
        _require_nonblank("linked_account_id", linked_account_id)
        if idempotency_key is not None:
            _require_nonblank("idempotency_key", idempotency_key)
            if len(idempotency_key) > 200:
                raise ConfigurationError("idempotency_key must contain at most 200 characters")
        for model in expected_developer_generations:
            _require_model(model)
        for model in mappings:
            _require_model(model)
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
        _require_nonblank("job_id", job_id)
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
        _require_model(model)
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("linked_account_id", linked_account_id)
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
        seen = {cursor} if cursor is not None else set()
        while True:
            page = self.list_records(model, cursor=cursor, **params)
            yield from page["records"]
            next_cursor = page["nextCursor"]
            if next_cursor is None:
                return
            if next_cursor in seen:
                raise OpenMergeError(
                    "OpenMerge record pagination returned a recurring cursor",
                )
            seen.add(next_cursor)
            cursor = next_cursor

    def _submit_record_action(
        self,
        model: str,
        action: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> Writeback:
        _require_model(model)
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("linked_account_id", linked_account_id)
        _validate_idempotency_key(idempotency_key)
        value = self._request(
            "POST",
            f"/unified/{quote(model, safe='')}/actions/{action}",
            body={
                "wsid": workspace_id,
                "linked_account_id": linked_account_id,
                **dict(payload),
            },
            idempotency_key=idempotency_key,
        )
        return cast(Writeback, value["write"])

    def create_record(
        self,
        model: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        changes: Mapping[str, Any],
        idempotency_key: str,
    ) -> Writeback:
        """Create one provider record through the connection-specific IR."""
        if not changes:
            raise ConfigurationError("changes must not be empty")
        return self._submit_record_action(
            model,
            "create",
            workspace_id=workspace_id,
            linked_account_id=linked_account_id,
            payload={"changes": dict(changes)},
            idempotency_key=idempotency_key,
        )

    def upsert_record(
        self,
        model: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        changes: Mapping[str, Any],
        idempotency_key: str,
        unified_id: Optional[str] = None,
    ) -> Writeback:
        """Create or update a record, optionally targeting an existing unified ID."""
        if not changes:
            raise ConfigurationError("changes must not be empty")
        if unified_id is not None:
            _require_nonblank("unified_id", unified_id)
        return self._submit_record_action(
            model,
            "upsert",
            workspace_id=workspace_id,
            linked_account_id=linked_account_id,
            payload={"unified_id": unified_id, "changes": dict(changes)},
            idempotency_key=idempotency_key,
        )

    def delete_record(
        self,
        model: str,
        unified_id: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        idempotency_key: str,
    ) -> Writeback:
        """Delete one provider record identified by its OpenMerge unified ID."""
        _require_nonblank("unified_id", unified_id)
        return self._submit_record_action(
            model,
            "delete",
            workspace_id=workspace_id,
            linked_account_id=linked_account_id,
            payload={"unified_id": unified_id},
            idempotency_key=idempotency_key,
        )

    def bulk_records(
        self,
        model: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        items: Sequence[BulkRecordActionItem],
        idempotency_key: str,
    ) -> Writeback:
        """Submit 1..100 homogeneous record actions as one governed operation."""
        serialized = _serialize_bulk_items(items)
        return self._submit_record_action(
            model,
            "bulk",
            workspace_id=workspace_id,
            linked_account_id=linked_account_id,
            payload={"items": serialized},
            idempotency_key=idempotency_key,
        )

    def create_custom_field(
        self,
        model: str,
        *,
        workspace_id: str,
        linked_account_id: str,
        definition: CustomFieldDefinition,
        idempotency_key: str,
    ) -> Writeback:
        """Create a portable provider custom field through the connector plugin."""
        if not definition:
            raise ConfigurationError("definition must not be empty")
        _require_nonblank("definition.name", definition.get("name", ""))
        return self._submit_record_action(
            model,
            "custom-fields",
            workspace_id=workspace_id,
            linked_account_id=linked_account_id,
            payload={"definition": dict(definition)},
            idempotency_key=idempotency_key,
        )

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
        _require_model(model)
        _require_nonblank("unified_id", unified_id)
        _require_nonblank("workspace_id", workspace_id)
        _require_nonblank("linked_account_id", linked_account_id)
        _validate_idempotency_key(idempotency_key)
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
        _require_nonblank("write_id", write_id)
        _require_nonblank("workspace_id", workspace_id)
        value = self._request(
            "GET", f"/unified/writes/{quote(write_id, safe='')}", query={"wsid": workspace_id}
        )
        return cast(Writeback, value["write"])

    def wait_for_writeback(
        self,
        write_id: str,
        workspace_id: str,
        *,
        interval_seconds: float = 1.0,
        timeout_seconds: float = 60.0,
        terminal_states: Sequence[str] = ("completed", "failed", "dispatch_failed"),
    ) -> Writeback:
        """Poll a writeback against a monotonic deadline until it is terminal."""
        _require_nonblank("write_id", write_id)
        _require_nonblank("workspace_id", workspace_id)
        if not math.isfinite(interval_seconds) or interval_seconds < 0.01:
            raise ConfigurationError("interval_seconds must be finite and at least 0.01")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be finite and positive")
        terminal = frozenset(terminal_states)
        if not terminal:
            raise ConfigurationError("terminal_states must not be empty")

        deadline = time.monotonic() + timeout_seconds
        while True:
            write = self.get_writeback(write_id, workspace_id)
            if write.get("state") in terminal:
                return write
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeoutError(
                    f"Writeback {write_id} did not reach a terminal state within "
                    f"{timeout_seconds:g} seconds",
                    timeout_seconds=timeout_seconds,
                )
            time.sleep(min(interval_seconds, remaining))
