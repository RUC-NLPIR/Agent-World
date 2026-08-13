# Hass-MCP — local MCP environment

This backend stores a local, queryable mirror of a Home Assistant instance: its entities, recent state history, automations, and diagnostic logs, plus an audit trail of control actions issued through the MCP tools. Core workflows include syncing HA state into the mirror, serving filtered/searchable reads, and recording service calls/restarts/actions with outcomes for troubleshooting and accountability.

Repository: https://github.com/voska/hass-mcp
Homepage: https://smithery.ai/server/@voska/hass-mcp

## Datastore

- `ha_instances.json` — Registered Home Assistant instances this MCP server can talk to, including version and connectivity status. (12 rows; fields: ['id', 'name', 'base_url', 'token_ref', 'ha_version', 'status', 'last_seen_at', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'offline', 'disabled']
  - constraint: unique(base_url)
  - constraint: name <> ''
  - constraint: base_url <> ''
  - constraint: token_ref <> ''
- `entities.json` — Materialized view of HA entities and their latest known state/attributes for fast listing, filtering, and field projection. (33 rows; fields: ['id', 'instance_id', 'entity_id', 'domain', 'friendly_name', 'state', 'attributes', 'last_changed_at', 'last_updated_at', 'last_synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unavailable', 'removed']
  - constraint: foreign key(instance_id) references ha_instances(id) on delete cascade
  - constraint: unique(instance_id, entity_id)
  - constraint: entity_id like '%.%'
  - constraint: domain = split_part(entity_id, '.', 1)
- `entity_state_history.json` — Append-only time series of entity state changes used to serve get_history(hours) and support summaries. (32 rows; fields: ['id', 'instance_id', 'entity_id', 'entity_pk', 'state', 'attributes', 'changed_at', 'source', 'created_at', 'updated_at'])
  - lifecycle `source`: ['ha_history_api', 'state_stream', 'manual_import']
  - constraint: foreign key(instance_id) references ha_instances(id) on delete cascade
  - constraint: foreign key(entity_pk) references entities(id) on delete set null
  - constraint: changed_at is not null
  - constraint: unique(instance_id, entity_id, changed_at)
- `automations.json` — Mirror of HA automations for list_automations and potential future control/inspection. (31 rows; fields: ['id', 'instance_id', 'automation_id', 'entity_id', 'alias', 'state', 'last_synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign key(instance_id) references ha_instances(id) on delete cascade
  - constraint: unique(instance_id, entity_id)
  - constraint: entity_id like 'automation.%'
- `operation_logs.json` — Audit trail for tool invocations that mutate or retrieve sensitive data, including HA service calls, entity actions, restarts, and log retrieval. (34 rows; fields: ['id', 'instance_id', 'tool_name', 'request', 'entity_id', 'service_domain', 'service_name', 'response_summary', 'error_message', 'duration_ms', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(instance_id) references ha_instances(id) on delete cascade
  - constraint: duration_ms is null or (duration_ms >= 0 and duration_ms <= 300000)
  - constraint: tool_name in ('get_version','get_entity','entity_action','list_entities','search_entities_tool','domain_summary_tool','system_overview','list_automations','restart_ha','call_service_tool','get_history','get_error_log')
  - constraint: tool_name != 'call_service_tool' or (service_domain is not null and service_name is not null)

## Business rules enforced by the tools

- All tools operate against a single active ha_instances row; if multiple exist, the system must select a default instance deterministically (e.g., lowest created_at) or require configuration.
- get_version returns ha_instances.ha_version; if null or stale, the service must fetch from HA and update ha_instances.ha_version, last_seen_at, updated_at, and record an operation_logs row.
- get_entity(entity_id, fields, detailed) reads entities by unique(instance_id, entity_id). If not found or status=removed, return a not-found error and log operation_logs.status=failed.
- Field projection for get_entity/list_entities must support top-level fields (e.g., 'state') and attribute paths prefixed with 'attr.' (e.g., 'attr.brightness') sourced from entities.attributes; invalid field paths are ignored or rejected consistently (server-wide policy).
- list_entities(domain, search_query, limit, fields, detailed) filters by entities.domain when domain is provided, performs case-insensitive substring match over entities.entity_id, entities.friendly_name, and JSON-text of entities.attributes when search_query is provided, and enforces 1 <= limit <= 500.
- search_entities_tool(query, limit) is equivalent to list_entities with search_query=query and no domain filter; it must enforce 1 <= limit <= 200 and return total count metadata based on the same filter.
- domain_summary_tool(domain, example_limit) must compute state distribution from entities where entities.domain=domain and status!='removed'; enforce 1 <= example_limit <= 20 and sample up to example_limit entities per distinct state.
- system_overview aggregates counts/distributions across all entities with status!='removed', returns per-domain counts, representative samples (2-3) per domain, common attributes per domain derived from frequent keys in entities.attributes, and may include area distribution if area data is present in attributes (no separate areas table).
- list_automations reads automations where status='active' for the instance; if the mirror is stale, the service may refresh from HA and upsert by unique(instance_id, entity_id).
- entity_action(entity_id, action, params) must validate action in {'on','off','toggle'} and translate to HA service calls; the raw tool param 'params' is stored in operation_logs.request as provided and additionally parsed into JSON for the outgoing HA call (reject if not valid JSON when required by implementation).
- call_service_tool(domain, service, data) must require non-empty domain and service; data may be null or an object; it must be persisted to operation_logs.request and used verbatim for the HA service call.
- restart_ha must create an operation_logs row and only allow execution when ha_instances.status in {'active','degraded'}; upon success it should set ha_instances.status='degraded' and last_seen_at=now until connectivity is re-established.
- get_history(entity_id, hours) must enforce 1 <= hours <= 168 and return rows from entity_state_history where instance_id matches and entity_id matches and changed_at >= now - hours; it must return count, first_changed=min(changed_at), and states ordered ascending by changed_at.
- History ingestion must guarantee uniqueness(instance_id, entity_id, changed_at); on conflict it must not create duplicates and may update attributes/state only if the incoming payload is newer/more complete.
- get_error_log may store only response_summary metadata in operation_logs; full log text must not be persisted in the database by default (to avoid uncontrolled growth and sensitive retention).
- All tool invocations must create an operation_logs row with status transitions queued->running->(succeeded|failed|cancelled) and must record error_message on failure.
- FK integrity must be enforced: deleting a ha_instances row cascades deletes to entities, entity_state_history (via instance_id), automations, and operation_logs; deleting an entities row sets entity_state_history.entity_pk to null.