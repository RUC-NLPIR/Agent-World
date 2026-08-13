# ABAP Development Tools Server — local MCP environment

This backend powers an ABAP Development Tools (ADT) server that connects to one or more SAP ABAP systems and exposes read-only retrieval and quick-search of ABAP repository objects (programs, classes, interfaces, function groups/modules, includes, packages, DDIC tables/structures, type info) plus table content reads. The main workflows are: authenticate a caller, route the request to a configured SAP system, fetch object metadata/source/definitions or run a quick search, and persist an audit trail of requests and responses for observability and governance.

Repository: https://github.com/mario-andreschak/mcp-abap-adt
Homepage: https://smithery.ai/server/@mario-andreschak/mcp-abap-adt

## Datastore

- `adt_systems.json` — Configured SAP ABAP systems (ADT endpoints) the server can talk to, including connection and policy settings. (12 rows; fields: ['id', 'name', 'base_url', 'client', 'verify_tls', 'default_language', 'default_abap_language_version', 'allow_table_reads', 'table_read_row_limit', 'allow_quick_search', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(name)
  - constraint: unique(base_url, client)
  - constraint: table_read_row_limit >= 0
  - constraint: default_language in /^[A-Z]{2}$/ when not null
- `api_keys.json` — API keys used by clients to access the ADT server, scoped to one ADT system and governed by quotas. (27 rows; fields: ['id', 'system_id', 'key_prefix', 'key_hash', 'name', 'allowed_tools', 'allow_table_reads', 'requests_per_minute_limit', 'requests_per_day_limit', 'status', 'expires_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: foreign key(system_id) references adt_systems(id)
  - constraint: unique(system_id, name)
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 0
- `abap_objects.json` — Normalized catalog of ABAP repository objects discovered/read via ADT. Acts as a metadata index and a cache anchor for source and definitions. (32 rows; fields: ['id', 'system_id', 'object_type', 'name', 'package_name', 'uri', 'description', 'is_standard', 'status', 'last_indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['known', 'stale', 'deleted']
  - constraint: foreign key(system_id) references adt_systems(id)
  - constraint: unique(system_id, object_type, name)
  - constraint: name <> ''
  - constraint: uri is null or uri like '/sap/bc/adt/%'
- `abap_object_artifacts.json` — Versioned artifacts for ABAP objects: source code, DDIC definitions, package details, and table contents snapshots. Supports caching and auditability of tool outputs. (36 rows; fields: ['id', 'object_id', 'artifact_kind', 'content_type', 'payload_text', 'payload_json', 'etag', 'retrieved_at', 'retrieved_by_key_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'superseded', 'purged']
  - constraint: foreign key(object_id) references abap_objects(id)
  - constraint: foreign key(retrieved_by_key_id) references api_keys(id)
  - constraint: artifact_kind = 'SOURCE' implies payload_text is not null
  - constraint: artifact_kind in ('DDIC_SCHEMA','PACKAGE_DETAILS','TYPEINFO','TABLE_CONTENTS') implies payload_json is not null
- `tool_requests.json` — Audit log of each tool invocation (including searches), its routing, outcome, and basic response metadata. Enables rate limiting, troubleshooting, and governance. (33 rows; fields: ['id', 'api_key_id', 'system_id', 'tool_name', 'request_params', 'resolved_object_id', 'http_status', 'duration_ms', 'error_code', 'error_message', 'result_artifact_id', 'status', 'requested_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'rejected']
  - constraint: foreign key(api_key_id) references api_keys(id)
  - constraint: foreign key(system_id) references adt_systems(id)
  - constraint: foreign key(resolved_object_id) references abap_objects(id)
  - constraint: foreign key(result_artifact_id) references abap_object_artifacts(id)

## Business rules enforced by the tools

- Every tool invocation MUST create a tool_requests row with status=received before executing any upstream ADT call.
- A tool_requests row MUST transition status according to its lifecycle transitions; skipping directly from received to succeeded is not allowed.
- api_keys.status must be 'active' and (expires_at is null or expires_at > now()) to accept a request; otherwise the request MUST be recorded with status=rejected and error_code in ('KEY_REVOKED','KEY_EXPIRED').
- Requests MUST be rate limited per api_key_id using tool_requests.requested_at: requests in the last 60 seconds MUST NOT exceed api_keys.requests_per_minute_limit; daily requests MUST NOT exceed api_keys.requests_per_day_limit. Exceeding limits MUST record status=rejected with error_code='RATE_LIMITED'.
- tool_requests.system_id MUST equal api_keys.system_id unless explicit multi-system routing is enabled (not modeled here); otherwise reject with error_code='SYSTEM_MISMATCH'.
- GetTableContents MUST be rejected unless both adt_systems.allow_table_reads and api_keys.allow_table_reads are true; otherwise status=rejected with error_code='TABLE_READS_DISABLED'.
- SearchObject MUST be rejected when adt_systems.allow_quick_search=false; otherwise status=rejected with error_code='SEARCH_DISABLED'.
- All retrieval tools (GetProgram/GetClass/GetInterface/GetFunctionGroup/GetFunction/GetInclude) MUST upsert an abap_objects row (system_id, object_type, name) on success and write an abap_object_artifacts row with artifact_kind='SOURCE' and status='current'. Previous 'current' artifacts for the same (object_id, artifact_kind) MUST be marked 'superseded'.
- DDIC tools (GetTable/GetStructure) MUST upsert abap_objects with object_type in ('DDIC_TABLE','DDIC_STRUCTURE') and store an artifact_kind='DDIC_SCHEMA' payload_json on success.
- GetPackage MUST upsert abap_objects with object_type='PACKAGE' and store artifact_kind='PACKAGE_DETAILS' payload_json on success.
- GetTypeInfo MUST upsert abap_objects with object_type='TYPEINFO' and store artifact_kind='TYPEINFO' payload_json on success.
- GetTableContents MUST upsert abap_objects with object_type='DDIC_TABLE' and store artifact_kind='TABLE_CONTENTS' payload_json on success; the number of returned rows MUST be <= adt_systems.table_read_row_limit.
- On any upstream ADT failure, tool_requests MUST be marked failed with http_status set when available; no artifact is written unless a partial cached artifact is explicitly flagged (not supported here).
- Secrets MUST NOT be stored in tool_requests.request_params; only object identifiers, search strings, paging/sort controls, and other non-sensitive parameters may be logged.