# Grafana Server — local MCP environment

This backend models a Grafana "server connector" that exposes read/write access to Grafana resources (dashboards, datasources, alerting, incidents) plus query execution against observability backends (Loki/Prometheus/Tempo) and investigation artifacts (Sift). The main workflows are: (1) catalog and search Grafana configuration objects, (2) execute time-bounded queries/analyses against datasources and store results for later retrieval, and (3) manage incident lifecycle and on-call context while auditing all actions initiated through the API connector.

Repository: https://github.com/pradeeppai/mcp-grafana
Homepage: https://smithery.ai/server/@pradeeppai/mcp-grafana

## Datastore

- `grafana_instances.json` — Configured Grafana endpoints/tenants that this service talks to, including auth configuration and org context. All other entities are scoped to an instance. (12 rows; fields: ['id', 'name', 'base_url', 'org_id', 'auth_type', 'auth_ref', 'status', 'default_time_range_seconds', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(name)
  - constraint: base_url must be a valid URL
  - constraint: default_time_range_seconds between 60 and 604800
- `grafana_resources.json` — Cache/index of Grafana configuration resources: dashboards, datasources, alert rules, contact points, and teams. Stores enough metadata to serve list/search/get tools quickly while allowing refresh from Grafana when needed. (31 rows; fields: ['id', 'instance_id', 'resource_type', 'uid', 'numeric_id', 'name', 'title', 'folder_uid', 'folder_title', 'type', 'url', 'tags', 'labels', 'is_default', 'state', 'spec', 'spec_etag', 'last_synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'stale']
  - constraint: foreign key (instance_id) references grafana_instances(id)
  - constraint: unique(instance_id, resource_type, uid) where uid is not null
  - constraint: unique(instance_id, resource_type, numeric_id) where numeric_id is not null
  - constraint: tags default to []
- `incidents.json` — Grafana Incident Management incidents created/read/updated through the connector, including label metadata and activity stream pointers. (27 rows; fields: ['id', 'instance_id', 'grafana_incident_id', 'title', 'severity', 'status', 'room_prefix', 'labels', 'is_drill', 'grafana_url', 'opened_at', 'resolved_at', 'created_by', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'resolved', 'cancelled']
  - constraint: foreign key (instance_id) references grafana_instances(id)
  - constraint: unique(instance_id, grafana_incident_id)
  - constraint: labels default to {}
  - constraint: is_drill default false
- `incident_activities.json` — Activity stream entries posted to incidents via the connector (comments, timeline updates, links). Supports add_activity_to_incident and auditing. (33 rows; fields: ['id', 'incident_id', 'grafana_activity_id', 'activity_type', 'body', 'metadata', 'posted_by', 'posted_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'sent', 'failed']
  - constraint: foreign key (incident_id) references incidents(id) on delete cascade
  - constraint: metadata default to {}
  - constraint: If activity_type in ('comment','note') then body is required
  - constraint: If status='failed' then error_message is required
- `observability_jobs.json` — Asynchronous query/analysis jobs executed against Grafana-backed datasources and investigation systems. Covers Loki/Prometheus/Tempo queries, label discovery, stats, and Sift/slow/error-pattern analyses, storing normalized inputs and results for retrieval. (35 rows; fields: ['id', 'instance_id', 'job_type', 'datasource_uid', 'datasource_type', 'query_text', 'label_name', 'series_selectors', 'regex_filter', 'time_start', 'time_end', 'step_seconds', 'limit', 'direction', 'page_cursor', 'page_limit', 'sift_investigation_uuid', 'sift_analysis_uuid', 'assertion_entity', 'result', 'status', 'error_message', 'started_at', 'finished_at', 'created_by', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (instance_id) references grafana_instances(id)
  - constraint: series_selectors default to []
  - constraint: limit between 1 and 5000 when provided
  - constraint: page_limit between 1 and 500 when provided
- `oncall_directory.json` — Mirror of Grafana OnCall directory entities (teams, schedules, shifts, users) needed to serve list/get/current-oncall tools with caching and pagination support. (30 rows; fields: ['id', 'instance_id', 'entity_type', 'oncall_id', 'name', 'username', 'team_id', 'schedule_id', 'timezone', 'shift_ids', 'shift_start', 'shift_end', 'details', 'last_synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'stale']
  - constraint: foreign key (instance_id) references grafana_instances(id)
  - constraint: unique(instance_id, entity_type, oncall_id)
  - constraint: shift_ids default to []
  - constraint: If entity_type='schedule' then name, timezone are required

## Business rules enforced by the tools

- All tool calls must be scoped to exactly one grafana_instances row; if multiple instances exist, the service must have a deterministic selection rule (e.g., configured default) and record created_by when available.
- get_dashboard_by_uid/get_alert_rule_by_uid/get_datasource_by_uid must resolve (instance_id, resource_type, uid) in grafana_resources; if cache is stale or missing, the implementation must fetch from Grafana and upsert spec, spec_etag, last_synced_at, status='active'.
- get_datasource_by_name must resolve by (instance_id, resource_type='datasource', name) with exact match; if multiple match, the call must fail with a deterministic error (ambiguity).
- search_dashboards must query grafana_resources where resource_type='dashboard' and (title ILIKE query OR tags contains query) and status='active'; return folder/title/url fields from cached metadata.
- update_dashboard must upsert grafana_resources row with resource_type='dashboard' and uid from Grafana response; spec must store the full dashboard model; status must be 'active'.
- list_datasources must filter grafana_resources by resource_type='datasource' and optional type; return id/uid/name/type/is_default; rows with status!='active' must be excluded.
- list_alert_rules must filter grafana_resources by resource_type='alert_rule', optional label selector predicates applied against labels object, and paginate using page_cursor/page_limit at the API layer; state must be returned from the cached state field when present.
- list_contact_points must filter grafana_resources by resource_type='contact_point' and optional exact name match; limit must cap at 500 even if caller requests more.
- create_incident must insert into incidents with status='active' unless explicitly created resolved/cancelled (if supported); it must require title, severity, and room_prefix at runtime even if the tool schema omits parameters.
- add_activity_to_incident must create an incident_activities row with status='queued', then attempt delivery; on success set status='sent' and posted_at; on failure set status='failed' with error_message.
- get_incident/list_incidents must read from incidents and may refresh from Grafana; list_incidents must support filtering by status in ('active','resolved') and optionally include drills by is_drill.
- list_oncall_* and get_oncall_shift/get_current_oncall_users must read from oncall_directory; if last_synced_at is older than a configured TTL, the implementation must refresh before responding.
- query_loki_logs/query_prometheus/query_loki_stats/list_*_label_* operations must create an observability_jobs row capturing all effective defaults (time range, limit, direction, selectors) and persist the normalized result in result when succeeded.
- find_error_pattern_logs and find_slow_requests must run as asynchronous observability_jobs (job_type='loki_find_error_pattern_logs'/'tempo_find_slow_requests') that transition queued->running->succeeded/failed; callers block/poll until finished_at is set or a maximum timeout is reached.
- query_loki_stats must validate that query_text is a simple label selector; if it contains line filters or pipeline stages, the job must be rejected before execution.
- Sift tools must store investigation and analysis payloads in observability_jobs.result keyed by sift_investigation_uuid/sift_analysis_uuid; get_sift_analysis must require both UUIDs to match a single job result or trigger a refresh job.
- All writes (update_dashboard, create_incident, add_activity_to_incident) must be idempotent where possible: repeated calls with the same external Grafana IDs should not create duplicate incidents/activities (enforced via unique(instance_id, grafana_incident_id) and best-effort dedupe on grafana_activity_id).
- Hard limits: observability_jobs.result payload must be truncated or summarized if it exceeds a configured size threshold (e.g., 1MB) and the job must record a flag inside result like {"truncated": true}.