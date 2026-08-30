from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

WidgetColorMode = Literal["dark", "light", "system"]
WidgetDensity = Literal["compact", "comfortable"]
WidgetMode = Literal["connect", "manager", "field-mapping", "sync-status"]
DeveloperFieldType = Literal[
    "string", "number", "integer", "boolean", "datetime", "date", "object", "array", "enum"
]
DeveloperFieldDirection = Literal["read_only", "write_only", "two_way"]
DeveloperFieldSensitivity = Literal["none", "pii", "secret"]
DeveloperFieldOverrideActor = Literal["application", "customer"]
WebhookTimestamp = Union[str, float]
RecordActionOperation = Literal["create", "update", "upsert", "delete"]
PortableCustomFieldType = Literal[
    "text",
    "long_text",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "enum",
    "multi_enum",
    "email",
    "phone",
    "url",
]
RecordWebhookEvent = Literal["record.created", "record.updated", "record.deleted"]
DomainWebhookEvent = Literal[
    "linked_account.created",
    "linked_account.reconnected",
    "sync.running",
    "sync.completed",
    "sync.failed",
    "sync.deletions_inferred",
    "writeback.state",
    "provider.schema.drift_detected",
    "provider.schema.drift_resolved",
    "changeset.approved",
    "changeset.merged",
    "model_migration.dispatched",
    "agent.job.completed",
    "workspace.invite.created",
    "workspace.member.joined",
    "webhook.endpoint.created",
    "webhook.endpoint.updated",
    "webhook.endpoint.disabled",
]
# Compatibility alias for dispatch code that deliberately accepts future
# server event kinds. The concrete envelope families below remain narrowed to
# the current public event vocabulary.
WebhookEvent = str


class WidgetColors(TypedDict, total=False):
    primary: str
    background: str
    panel: str
    surface: str
    surfaceHover: str
    border: str
    borderStrong: str
    text: str
    muted: str
    danger: str


class WidgetTypography(TypedDict, total=False):
    fontFamily: str
    scale: float


class WidgetShape(TypedDict, total=False):
    radius: float


class WidgetBranding(TypedDict, total=False):
    productName: str
    logoUrl: str


class WidgetAppearance(TypedDict, total=False):
    """Canonical wire-format design tokens for hosted and embedded widgets."""

    mode: WidgetColorMode
    density: WidgetDensity
    colors: WidgetColors
    typography: WidgetTypography
    shape: WidgetShape
    branding: WidgetBranding


class _LinkTokenBase(TypedDict):
    token: str
    expiresIn: int
    hostedUrl: str


class LinkToken(_LinkTokenBase):
    pass


class MappingLinkToken(LinkToken):
    discoveryJobId: str


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


class SyncRun(TypedDict, total=False):
    id: str
    workflow_id: str
    state: str


class AccountTransition(TypedDict, total=False):
    id: str
    status: str
    cancelled_runs: int
    runs: List[SyncRun]


class AccountSchedule(TypedDict, total=False):
    id: str
    cadence_seconds: int
    scheduled_models: List[str]
    reconciliation_seconds_by_model: Dict[str, int]


class AccountDeletion(TypedDict):
    deleted: bool
    cancelled_runs: int
    erasure_job_id: str
    erasure_state: str


class DeveloperIRField(TypedDict, total=False):
    type: DeveloperFieldType
    format: str
    nullable: bool
    items: Dict[str, Any]
    values: List[str]
    ref: str
    sensitivity: DeveloperFieldSensitivity
    description: str
    label: str
    required: bool
    direction: DeveloperFieldDirection
    default_provider_field: str
    override_by: List[DeveloperFieldOverrideActor]


class DeveloperIRDocumentField(TypedDict, total=False):
    """A field as materialized in the immutable/effective IR document."""

    type: DeveloperFieldType
    format: str
    nullable: bool
    items: Dict[str, Any]
    values: List[str]
    ref: str
    sensitivity: DeveloperFieldSensitivity
    description: str
    mapping: Dict[str, Any]
    added_by: str


class DeveloperIRProvenance(TypedDict, total=False):
    author: str
    created_at: str
    reason: str
    evidence: str


class DeveloperIRModelRef(TypedDict, total=False):
    ref: str
    scope: str
    version: int


class DeveloperIRDocument(TypedDict, total=False):
    kind: Literal["model"]
    id: str
    version: int
    category: str
    scope: str
    extends: DeveloperIRModelRef
    fields: Dict[str, DeveloperIRDocumentField]
    provenance: DeveloperIRProvenance


class DeveloperIRRequirement(TypedDict, total=False):
    required: bool
    direction: DeveloperFieldDirection
    label: str
    default_provider_field: Optional[str]
    override_by: List[DeveloperFieldOverrideActor]


class DeveloperIR(TypedDict, total=False):
    wsid: str
    oauth_app_id: str
    provider: Optional[str]
    model_id: str
    generation: int
    base_hash: str
    document_hash: str
    contract_hash: str
    inherited: bool
    document: DeveloperIRDocument
    base_document: DeveloperIRDocument
    requirements: Dict[str, DeveloperIRRequirement]
    removed_fields: List[str]
    actor_id: str
    created_at: WebhookTimestamp
    updated_at: Optional[WebhookTimestamp]


class DeveloperIRRevision(TypedDict, total=False):
    head_id: str
    wsid: str
    provider: Optional[str]
    oauth_app_id: str
    model_id: str
    generation: int
    base_hash: str
    document_hash: str
    contract_hash: str
    document: DeveloperIRDocument
    requirements: Dict[str, DeveloperIRRequirement]
    removed_fields: List[str]
    actor_id: str
    created_at: WebhookTimestamp


class DeveloperIRRevisionPage(TypedDict):
    revisions: List[DeveloperIRRevision]


class _WebhookWorkspaceContextRequired(TypedDict):
    id: str


class WebhookWorkspaceContext(_WebhookWorkspaceContextRequired, total=False):
    name: Optional[str]


class WebhookUserContext(TypedDict):
    origin_id: Optional[str]
    actor_id: Optional[str]


class WebhookIntegrationContext(TypedDict):
    provider: Optional[str]
    name: Optional[str]
    categories: List[str]


class _WebhookOAuthAppContextRequired(TypedDict):
    id: Optional[str]


class WebhookOAuthAppContext(_WebhookOAuthAppContextRequired, total=False):
    name: Optional[str]


class WebhookConnectionContext(TypedDict):
    id: Optional[str]


class WebhookContext(TypedDict):
    workspace: WebhookWorkspaceContext
    user: WebhookUserContext
    integration: WebhookIntegrationContext
    oauth_app: WebhookOAuthAppContext
    connection: WebhookConnectionContext


class RecordWebhookConnectionContext(TypedDict):
    id: str


class RecordWebhookWorkspaceContext(TypedDict):
    id: str
    name: Optional[str]


class RecordWebhookOAuthAppContext(TypedDict):
    id: Optional[str]
    name: Optional[str]


class RecordWebhookContext(TypedDict):
    workspace: RecordWebhookWorkspaceContext
    user: WebhookUserContext
    integration: WebhookIntegrationContext
    oauth_app: RecordWebhookOAuthAppContext
    connection: RecordWebhookConnectionContext


class RecordWebhookData(TypedDict):
    model: str
    remote_id: str
    unified_id: str
    record: Dict[str, Any]
    deleted_at: Optional[WebhookTimestamp]


class RecordWebhookPlan(TypedDict):
    generation: Optional[int]
    hash: Optional[str]


class RecordWebhookBreadcrumbs(TypedDict):
    event_id: str
    occurred_at: str
    content_hash: str
    sync_run_id: Optional[str]
    source_cursor: Any
    source_updated_at: Optional[WebhookTimestamp]
    plan: RecordWebhookPlan


class RecordWebhookEnvelope(TypedDict):
    """High-frequency Scylla CDC record delivery from record-eventd."""

    event: RecordWebhookEvent
    ctx: RecordWebhookContext
    data: RecordWebhookData
    breadcrumbs: RecordWebhookBreadcrumbs


class DomainWebhookEntity(TypedDict):
    type: Optional[str]
    id: Optional[str]


class DomainWebhookBreadcrumbs(TypedDict):
    event_id: str
    occurred_at: Optional[str]
    entity: DomainWebhookEntity
    request_id: Optional[str]


class DomainWebhookEnvelope(TypedDict):
    """Low-frequency control-plane event from the durable telemetry outbox."""

    event: DomainWebhookEvent
    ctx: WebhookContext
    data: Dict[str, Any]
    breadcrumbs: DomainWebhookBreadcrumbs


# Compatibility aliases retained for applications already importing the
# original record-envelope component names.
WebhookData = RecordWebhookData
WebhookPlan = RecordWebhookPlan
WebhookBreadcrumbs = RecordWebhookBreadcrumbs
WebhookEnvelope = Union[RecordWebhookEnvelope, DomainWebhookEnvelope]


class ConnectionMappingLinkedAccount(TypedDict):
    id: str
    provider: str
    provider_display_name: str


class ConnectionMappingOAuthApp(TypedDict):
    id: str
    name: str


ConnectionMappingBindingSource = Literal["application", "connection", "default", "unmapped"]


class ConnectionMappingField(TypedDict, total=False):
    id: str
    label: str
    type: DeveloperFieldType
    format: str
    nullable: bool
    items: Dict[str, Any]
    values: List[str]
    ref: str
    sensitivity: DeveloperFieldSensitivity
    description: str
    required: bool
    direction: DeveloperFieldDirection
    default_provider_field: Optional[str]
    override_by: List[DeveloperFieldOverrideActor]
    application_overridable: bool
    customer_editable: bool
    mapped_to: Optional[str]
    binding_source: ConnectionMappingBindingSource
    binding_error: Optional[str]


class ConnectionMappingProviderOption(TypedDict, total=False):
    value: Any
    label: str
    active: bool
    default: bool
    id: str


class ConnectionMappingProviderField(TypedDict, total=False):
    """Stable mapping semantics plus connector-specific descriptive metadata."""

    path: str
    type: str
    canonical_type: DeveloperFieldType
    compatible_canonical_types: List[DeveloperFieldType]
    label: str
    readable: bool
    createable: bool
    updateable: Optional[bool]
    nullable: bool
    required: bool
    options: List[ConnectionMappingProviderOption]
    length: int
    byte_length: int
    precision: int
    scale: int
    digits: int
    reference_to: Union[str, List[str]]
    collection_format: str
    description: str
    ui_type: str
    group: str
    unique: bool
    calculated: bool
    system: bool
    archived: bool
    custom: bool
    defaulted_on_create: bool
    relationship_name: str
    external_id: bool
    compound_field_name: str
    sortable: bool
    filterable: bool
    groupable: bool
    name_field: bool
    auto_number: bool
    searchable: bool
    virtual: bool
    webhook: bool
    mass_update: bool


class ConnectionMappingModel(TypedDict):
    id: str
    developer_ir_generation: int
    developer_ir_hash: str
    fields: List[ConnectionMappingField]
    provider_fields: List[ConnectionMappingProviderField]
    schema_observed_at: Optional[str]
    schema_ready: bool


class ConnectionMappingSchema(TypedDict, total=False):
    linked_account: ConnectionMappingLinkedAccount
    oauth_app: ConnectionMappingOAuthApp
    status: str
    required: bool
    models: List[ConnectionMappingModel]
    generated_at: str


class ConnectionMappingActivatedModel(TypedDict):
    generation: int
    plan_hash: str
    developer_ir_generation: int
    mapped_fields: int


class ConnectionMappingResult(TypedDict, total=False):
    action: Literal["discover", "activate"]
    workspace_id: str
    linked_account_id: str
    provider: str
    models: Union[Dict[str, int], Dict[str, ConnectionMappingActivatedModel]]
    start_initial_sync: bool
    initial_sync_models: List[str]


class ConnectionMappingJob(TypedDict, total=False):
    id: str
    action: Literal["discover", "activate"]
    state: str
    linked_account_id: str
    models: List[str]
    result: ConnectionMappingResult
    error_type: str
    error: str
    created_at: WebhookTimestamp
    updated_at: WebhookTimestamp
    finished_at: WebhookTimestamp


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
    provider: Optional[str]
    model: str
    unified_id: str
    data: Dict[str, Any]
    remote_data: Any
    deleted_at: Optional[float]
    deletion_source: Optional[str]
    updated_at: Optional[float]


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


class _BulkRecordActionItemRequired(TypedDict):
    operation: RecordActionOperation


class BulkRecordActionItem(_BulkRecordActionItemRequired, total=False):
    unified_id: str
    remote_id: str
    changes: Dict[str, Any]


class _CustomFieldDefinitionRequired(TypedDict):
    name: str


class CustomFieldDefinition(_CustomFieldDefinitionRequired, total=False):
    label: str
    type: PortableCustomFieldType
    description: str
    options: List[str]
    length: int
    precision: int
    scale: int
    required: bool
