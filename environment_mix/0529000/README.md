# Swagger MCP Server — local MCP environment

This backend stores ingested Swagger/OpenAPI documents (including cached fetches) and derived artifacts: parsed operation indexes, generated code outputs, and reusable code-generation templates. Main workflows are: (1) fetch+parse an OpenAPI document (optionally cached/filtered) and return operation info, (2) generate TypeScript types or API clients from a parsed spec and persist generation jobs and outputs, (3) manage custom templates and write generated content to filesystem paths with auditing.

Repository: https://github.com/tuskermanshu/swagger-mcp-server
Homepage: https://smithery.ai/server/@tuskermanshu/swagger-mcp-server

## Datastore

- `openapi_documents.json` — Canonical registry of Swagger/OpenAPI documents referenced by URL, including fetch metadata, raw content snapshots, and cache lifecycle for optimized parsing/generation. (37 rows; fields: ['id', 'url', 'url_normalized', 'last_request_headers', 'etag', 'last_modified', 'content_type', 'http_status', 'fetch_error', 'raw_bytes', 'raw_body', 'content_sha256', 'openapi_version', 'title', 'version', 'status', 'cache_expires_at', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'fetching', 'stale', 'failed', 'deleted']
  - constraint: unique(url_normalized)
  - constraint: raw_bytes >= 0
  - constraint: http_status is null OR (http_status >= 100 AND http_status <= 599)
  - constraint: cache_expires_at is null OR cache_expires_at >= created_at
- `openapi_parses.json` — A parse run over an OpenAPI document, capturing the parse mode and options (optimized/lite, schema/detail inclusion, validation flags, filters) and storing derived operation and schema summaries for fast subsequent reads. (45 rows; fields: ['id', 'document_id', 'mode', 'include_schemas', 'include_details', 'skip_validation', 'use_cache', 'cache_ttl_minutes', 'lazy_loading', 'filter_tag', 'path_prefix', 'parse_fingerprint', 'operation_count', 'schema_count', 'operations_index', 'schemas_blob', 'validation_errors', 'status', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: fk(document_id) references openapi_documents(id) on delete restrict
  - constraint: unique(parse_fingerprint)
  - constraint: cache_ttl_minutes is null OR (cache_ttl_minutes >= 0 AND cache_ttl_minutes <= 525600)
  - constraint: operation_count >= 0
- `codegen_templates.json` — Built-in and user-defined templates used for generating API clients, TypeScript types, and config files. Supports listing, retrieving, saving/updating, and deleting custom templates. (29 rows; fields: ['id', 'name', 'type', 'framework', 'content', 'description', 'is_builtin', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(type, framework, name) where status='active'
  - constraint: framework is null OR type in ('api-client','config-file')
  - constraint: type='typescript-types' implies framework is null
  - constraint: content length > 0
- `codegen_jobs.json` — Tracks code generation requests for TypeScript types and API clients, including all tool parameters, chosen templates, and produced output files (referenced via codegen_files). (37 rows; fields: ['id', 'document_id', 'parse_id', 'job_type', 'tool_variant', 'output_dir', 'overwrite', 'file_prefix', 'file_suffix', 'use_namespace', 'namespace', 'generate_enums', 'strict_types', 'exclude_schemas', 'include_schemas', 'generate_index', 'client_type', 'generate_type_imports', 'types_import_path', 'group_by', 'include_tags', 'exclude_tags', 'request_headers', 'use_cache', 'cache_ttl_minutes', 'skip_validation', 'lazy_loading', 'template_id', 'status', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(document_id) references openapi_documents(id) on delete restrict
  - constraint: fk(parse_id) references openapi_parses(id) on delete set null
  - constraint: fk(template_id) references codegen_templates(id) on delete set null
  - constraint: cache_ttl_minutes is null OR (cache_ttl_minutes >= 0 AND cache_ttl_minutes <= 525600)
- `filesystem_writes.json` — Audit log of file_writer actions and codegen output materialization to disk paths, including encoding, append semantics, and directory creation behavior. (34 rows; fields: ['id', 'job_id', 'file_path', 'content', 'create_dirs', 'append', 'encoding', 'bytes_written', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: fk(job_id) references codegen_jobs(id) on delete set null
  - constraint: length(file_path) >= 1
  - constraint: encoding in ('utf8','utf-8','ascii','base64','latin1','ucs2','utf16le')
  - constraint: bytes_written is null OR bytes_written >= 0

## Business rules enforced by the tools

- parse-swagger/parse-swagger-optimized/parse-swagger-lite must upsert an openapi_documents row by url_normalized; if useCache=true and cache_expires_at > now and raw_body is present, the server must not refetch and should reuse the cached content.
- When cacheTTLMinutes is provided, cache_expires_at must be set to now + cacheTTLMinutes minutes; cacheTTLMinutes must be in [0, 525600].
- parse-swagger-lite must store mode='lite'; parse-swagger-optimized must store mode='optimized'; parse-swagger must store mode='standard'.
- filterTag and pathPrefix, when provided, must be applied to the derived operations_index and the persisted operation_count must reflect the filtered result.
- If includeDetails=false, operations_index must not include full request/response bodies; if includeSchemas=false, schemas_blob must be null and schema_count must be 0.
- generate-typescript-types* must create a codegen_jobs row with job_type='typescript-types' and tool_variant matching the invoked tool; generate-api-client* must create a codegen_jobs row with job_type='api-client' and require client_type.
- For generate-api-client* jobs, groupBy must be one of ['tag','path','none']; includeTags/excludeTags filters must be applied to the set of operations used to generate output.
- template-list must only return templates where status='active' and must support filtering by type and (when provided) framework; includeContent=false must omit or null out content at response time without changing stored content.
- template-save must upsert codegen_templates by id; it must reject updates that would set status='deleted' implicitly and must enforce (type='typescript-types' => framework is null) and (framework non-null => type in ['api-client','config-file']).
- template-delete must soft-delete by setting status='deleted' and must reject deletion when is_builtin=true.
- file_writer must always create a filesystem_writes row; on success status='succeeded' and bytes_written must be populated; on failure status='failed' and error_message must be populated.
- If file_writer.append=false, repeated writes to the same file_path are allowed but must be represented as distinct filesystem_writes rows (audit log), not overwrites of existing rows.
- Foreign key integrity must be enforced: openapi_parses.document_id and codegen_jobs.document_id must reference existing openapi_documents; any parse_id used by a job must reference an openapi_parses row for the same document_id.