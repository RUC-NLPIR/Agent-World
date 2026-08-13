# Microsoft 365 Core Server — local MCP environment

This backend persists tenant-scoped Microsoft 365 administration operations initiated through the server (group/user/site/intune/compliance actions) and the resulting external Microsoft Graph/Exchange/Intune/Purview effects. It also stores audit-log search jobs and unified security/compliance objects (alerts, DLP artifacts, assessments/evidence) plus an internal operation ledger that powers retries, rate limiting, status tracking, and reporting across all tools.

Repository: https://github.com/DynamicEndpoints/m365-core-mcp
Homepage: https://smithery.ai/server/@DynamicEndpoints/m365-core-mcp

## Datastore

- `tenants.json` — Represents a Microsoft 365 tenant configured in the server, including the identity of the tenant and connection metadata needed to call Microsoft Graph/Exchange/Intune/Purview. All managed objects and operations are scoped to a tenant. (12 rows; fields: ['id', 'tenant_domain', 'azure_tenant_id', 'display_name', 'status', 'default_region', 'rate_limit_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deprovisioned']
  - constraint: unique(azure_tenant_id)
  - constraint: unique(tenant_domain)
  - constraint: rate_limit_per_minute IN (60,120,300,600,1200)
- `directory_entities.json` — Unified directory and resource catalog for objects the server manages or references (users, groups, apps, devices, sites, lists, intune objects, exchange artifacts). Stores external IDs and key properties so tools can locate and update resources consistently. (37 rows; fields: ['id', 'tenant_id', 'entity_type', 'external_id', 'display_name', 'principal_name', 'mail', 'enabled', 'status', 'properties', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'pending', 'deleted', 'error']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: unique(tenant_id, entity_type, external_id)
  - constraint: principal_name is required when entity_type IN ('user','exchange_mailbox','azuread_app_registration','service_principal')
  - constraint: enabled may be non-null only when entity_type IN ('user','device','intune_device_macos','intune_device_windows')
- `group_memberships.json` — Membership edges between directory entities for group management (distribution lists, security groups, M365 groups/Teams) and Azure AD role assignments (role -> member). Enables member add/remove/list operations and offboarding workflows. (29 rows; fields: ['id', 'tenant_id', 'container_entity_id', 'member_entity_id', 'membership_type', 'status', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'pending', 'removed', 'error']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(container_entity_id) references directory_entities(id) on delete cascade
  - constraint: fk(member_entity_id) references directory_entities(id) on delete cascade
  - constraint: unique(tenant_id, container_entity_id, member_entity_id, membership_type)
- `operations.json` — Internal operation ledger for every tool invocation and any downstream calls (Graph/ARM/Exchange). Powers retries, rate limiting, auditing, response formats, and long-running jobs (offboarding, policy creation, compliance runs). (36 rows; fields: ['id', 'tenant_id', 'tool_name', 'operation_kind', 'request_payload', 'target_entity_id', 'status', 'attempt_count', 'max_attempts', 'rate_limited', 'upstream_provider', 'upstream_request_count', 'response_format', 'response_payload', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partial']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(target_entity_id) references directory_entities(id) on delete set null
  - constraint: attempt_count >= 0
  - constraint: max_attempts BETWEEN 1 AND 10
- `audit_log_events.json` — Materialized subset of Microsoft 365 audit log events returned from search_audit_log operations. Stored for caching, pagination, reporting, and evidence collection. Events are associated to the operation that retrieved them. (39 rows; fields: ['id', 'tenant_id', 'retrieved_by_operation_id', 'event_time', 'workload', 'activity', 'user_principal_name', 'client_ip', 'resource_external_id', 'raw_event', 'created_at', 'updated_at'])
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(retrieved_by_operation_id) references operations(id) on delete cascade
  - constraint: event_time is not null
  - constraint: unique(tenant_id, retrieved_by_operation_id, event_time, activity, user_principal_name, client_ip)
- `compliance_records.json` — Tenant-scoped compliance program data used by manage_compliance_frameworks/assessments/monitoring/evidence/gap-analysis/CIS and report generation. Stores frameworks, controls, assessment runs, findings, evidence pointers, and generated reports as typed records. (36 rows; fields: ['id', 'tenant_id', 'record_type', 'external_id', 'name', 'status', 'parent_record_id', 'related_operation_id', 'score', 'severity', 'details', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'running', 'completed', 'archived', 'failed']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(parent_record_id) references compliance_records(id) on delete set null
  - constraint: fk(related_operation_id) references operations(id) on delete set null
  - constraint: unique(tenant_id, record_type, external_id) where external_id is not null

## Business rules enforced by the tools

- All tool executions MUST create an operations row with tool_name equal to the invoked tool, even when the tool parameters schema is empty; derived inputs (tenant, targets, filters, time ranges, formats) MUST be written to operations.request_payload.
- health_check MUST only read tenants and write an operations row with operation_kind='read'; it MUST NOT mutate directory_entities, memberships, audit_log_events, or compliance_records.
- Rate limiting: for each tenant, the server MUST prevent operations from transitioning queued->running if the number of upstream requests in the last rolling minute would exceed tenants.rate_limit_per_minute; such operations MUST set rate_limited=true while delayed.
- For manage_* group tools (distribution/security/m365), any add/remove member action MUST upsert group_memberships rows with membership_type='group_member' or 'group_owner' and status pending->active only after upstream confirmation; failures MUST set status='error' and preserve the previous active membership if it existed.
- manage_azuread_roles MUST represent role assignments as group_memberships with membership_type='role_member' where container_entity_id references a directory_entities row with entity_type='azuread_role'.
- manage_offboarding MUST be implemented as an operations workflow: it MUST create one parent operation (operation_kind='workflow') and one or more child operations recorded as separate operations rows whose request_payload.parent_operation_id equals the parent id; the parent operation status MUST be 'partial' if any child fails and at least one succeeds.
- search_audit_log MUST persist returned events into audit_log_events and link them to the retrieving operation; duplicate events for the same operation MUST be deduplicated by the unique constraint.
- create_intune_policy/createIntunePolicy/enhanced_create_intune_policy MUST create (or update) directory_entities entries of entity_type intune_policy_windows or intune_policy_macos; the canonical generated policy JSON MUST be stored in directory_entities.properties.policy_document and validated before the operation can be marked succeeded.
- manage_alerts/manage_dlp_* and manage_sensitivity_labels MUST maintain corresponding directory_entities entries (entity_type security_alert, purview_dlp_policy, purview_dlp_incident, purview_sensitivity_label) keyed by external_id; status updates MUST be reflected in directory_entities.properties.state while directory_entities.status remains 'active' unless the object is deleted.
- generate_audit_reports MUST write a compliance_records row of record_type='report' with related_operation_id set; the report MUST reference the source dataset via details.source_operation_ids (including search_audit_log operation ids) and MUST NOT include raw PII beyond what is present in audit_log_events.raw_event.