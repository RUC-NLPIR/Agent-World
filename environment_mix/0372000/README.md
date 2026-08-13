# DynamoDB Read-Only Server — local MCP environment

This backend powers a read-only DynamoDB gateway that enumerates tables, inspects table metadata, and executes read operations (scan/query/get-item) with pagination and counting. It stores the discovered DynamoDB catalog, snapshots of table schemas, and an audit log of read requests/results for observability, rate-limiting, and pagination token management.

Repository: https://github.com/jjikky/dynamo-readonly-mcp
Homepage: https://smithery.ai/server/@jjikky/dynamo-readonly-mcp

## Datastore

- `workspaces.json` — Represents an environment/tenant bound to a single AWS account+region (or logical grouping) whose DynamoDB tables can be read via the server. (12 rows; fields: ['id', 'name', 'aws_account_id', 'aws_region', 'status', 'max_requests_per_minute', 'max_page_size', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(name)
  - constraint: aws_account_id length = 12 and numeric
  - constraint: max_requests_per_minute between 1 and 60000
  - constraint: max_page_size between 1 and 1000
- `api_keys.json` — Credentials used to authenticate clients of the read-only server; keys are scoped to a workspace. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: FK workspace_id references workspaces.id on delete restrict
- `dynamodb_tables.json` — Catalog of DynamoDB tables visible to the server, per workspace. Populated/updated by background discovery and used to serve list/describe calls quickly. (33 rows; fields: ['id', 'workspace_id', 'table_name', 'table_arn', 'status', 'key_schema', 'attribute_definitions', 'billing_mode', 'provisioned_read_capacity_units', 'table_size_bytes', 'item_count', 'last_described_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'inaccessible']
  - constraint: unique(workspace_id, table_name)
  - constraint: table_size_bytes >= 0 when not null
  - constraint: item_count >= 0 when not null
  - constraint: provisioned_read_capacity_units >= 0 when not null
- `read_requests.json` — Audit log of read operations executed through the server (list/describe/scan/query/paginate/get-item/count). Also stores server-generated pagination tokens and request/response metadata. (36 rows; fields: ['id', 'workspace_id', 'api_key_id', 'table_id', 'operation', 'status', 'request_params', 'response_summary', 'result_items_sample', 'pagination_token_id', 'http_status_code', 'error_code', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed', 'rejected']
  - constraint: duration_ms >= 0 when not null
  - constraint: http_status_code between 100 and 599 when not null
  - constraint: operation in allowed set
  - constraint: If operation in ('scan-table','query-table','paginate-query-table','get-item','count-items','describe-table') then table_id is not null
- `pagination_tokens.json` — Server-managed continuation tokens for query pagination. Stores encrypted/encoded LastEvaluatedKey and the query context needed to safely resume. (35 rows; fields: ['id', 'workspace_id', 'table_id', 'operation', 'status', 'token_hash', 'encrypted_last_evaluated_key', 'query_fingerprint', 'expires_at', 'consumed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'consumed', 'expired', 'revoked']
  - constraint: unique(token_hash)
  - constraint: expires_at > created_at
  - constraint: FK workspace_id references workspaces.id on delete cascade
  - constraint: FK table_id references dynamodb_tables.id on delete cascade

## Business rules enforced by the tools

- Authentication: every request must be associated with an active api_keys row (status='active') and its workspace must be active (workspaces.status='active'); otherwise create a read_requests row with status='rejected'.
- list-tables must return dynamodb_tables rows filtered by workspace_id and status='active', ordered by table_name.
- describe-table must resolve the target table by (workspace_id, table_name) and refresh metadata if last_described_at is older than a configured TTL; if the AWS call fails with access/does-not-exist, set dynamodb_tables.status to 'inaccessible' or 'deleted' accordingly.
- scan-table and query-table must enforce workspace max_page_size: requested Limit (if provided in read_requests.request_params) must be <= workspaces.max_page_size; if absent, default to max_page_size.
- get-item must validate that the provided Key matches the table key_schema (partition key required; sort key required only if table has one); otherwise reject the request (read_requests.status='rejected').
- paginate-query-table must accept an opaque token that maps to pagination_tokens.token_hash; it must only succeed if the token is status='active', not expired (expires_at > now), and the provided query context fingerprint matches pagination_tokens.query_fingerprint; otherwise fail the request.
- Pagination tokens are single-use by default: on successful paginate-query-table, mark the consumed token as status='consumed' with consumed_at set, and if the response has a new LastEvaluatedKey create a new pagination_tokens row with status='active'.
- count-items must not return item bodies; it returns counts derived from DynamoDB Count/ScannedCount and stores them in read_requests.response_summary.
- All operations must write a read_requests row with operation, status, duration_ms, and normalized error fields when applicable.
- Rate limiting: within each workspace, the number of read_requests with status in ('received','succeeded','failed') in the last rolling minute must not exceed workspaces.max_requests_per_minute; excess must be rejected and logged.
- Data minimization: read_requests.result_items_sample must be capped (e.g., <= 10 items and <= 32KB total) and may be disabled per deployment; request_params must redact secrets if clients accidentally pass them.