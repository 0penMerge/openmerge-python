from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class LinkToken(TypedDict):
    token: str
    expiresIn: int
    hostedUrl: str


class LinkedAccount(TypedDict, total=False):
    id: str
    wsid: str
    provider: str
    provider_display_name: str
    end_user_origin_id: str
    end_user_label: str
    status: str
    last_sync_at: Optional[float]
    sync_count: int
    sync_cadence_seconds: int
    created_at: float
    mapping_status: str
    mapping_required: bool


class DeveloperIR(TypedDict, total=False):
    wsid: str
    oauth_app_id: str
    provider: Optional[str]
    model_id: str
    generation: int
    document_hash: str
    contract_hash: str
    inherited: bool
    document: Dict[str, Any]
    requirements: Dict[str, Dict[str, Any]]
    removed_fields: List[str]


class ConnectionMappingSchema(TypedDict, total=False):
    linked_account: Dict[str, Any]
    oauth_app: Dict[str, Any]
    status: str
    required: bool
    models: List[Dict[str, Any]]


class ConnectionMappingJob(TypedDict, total=False):
    id: str
    action: str
    state: str
    linked_account_id: str
    models: Any
    result: Dict[str, Any]
    error: str


class ConnectorDescriptor(TypedDict, total=False):
    id: str
    version: str
    name: str
    company: str
    description: str
    logo: Dict[str, Any]
    categories: List[str]
    capabilities: Dict[str, Any]
    auth: Dict[str, Any]
    setup: Dict[str, Any]


class ConnectorIntegration(TypedDict, total=False):
    provider: str
    manifest: Dict[str, Any]
    descriptor: ConnectorDescriptor
    callback_url: str
    configured: bool
    oauth_app_count: int
    linked_account_count: int


class UnifiedModelDefinition(TypedDict, total=False):
    id: str
    category: str
    version: Any
    fields: Dict[str, Dict[str, Any]]
    base_two_way_fields: int
    base_two_way_field_ids: List[str]
    base_two_way_field_ids_by_provider: Dict[str, List[str]]
    base_mapped_providers: int
    base_mapped_provider_ids: List[str]


class UnifiedRecord(TypedDict, total=False):
    wsid: str
    linked_account_id: str
    provider: str
    model: str
    unified_id: str
    data: Dict[str, Any]
    remote_data: Any
    deleted_at: Optional[float]


class UnifiedRecordPage(TypedDict):
    records: List[UnifiedRecord]
    nextCursor: Optional[str]


class Writeback(TypedDict, total=False):
    id: str
    workflow_id: str
    wsid: str
    linked_account_id: str
    provider: str
    model: str
    unified_id: str
    state: str
    result: Any
    error_type: str
    created_at: float
    updated_at: float
