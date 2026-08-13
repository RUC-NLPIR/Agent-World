# ntfy-me-mcp — local MCP environment

This backend models an ntfy-me MCP deployment that subscribes to one or more ntfy topics, ingests notifications from the upstream ntfy server, and caches them for later retrieval/search. The main workflows are: (1) deploy/register a server instance and its topic subscriptions, and (2) fetch cached notifications for the instance (optionally filtered in-memory by the tool implementation, since the tool surface exposes no parameters).

Repository: https://github.com/gitmotion/ntfy-me-mcp
Homepage: https://smithery.ai/server/@gitmotion/ntfy-me-mcp

## Datastore

- `servers.json` — Registered ntfy-me-mcp server instances (a deployed connector) and their runtime configuration used to ingest/cache notifications. (12 rows; fields: ['id', 'display_name', 'base_url', 'default_fetch_limit', 'status', 'last_ingest_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'active', 'paused', 'degraded', 'deleted']
  - constraint: unique(display_name)
  - constraint: base_url LIKE 'http%'
  - constraint: default_fetch_limit >= 1
  - constraint: default_fetch_limit <= 500
- `topic_subscriptions.json` — Topics on an ntfy server that a given ntfy-me-mcp instance ingests and caches messages from. (12 rows; fields: ['id', 'server_id', 'topic', 'status', 'since_event_id', 'last_polled_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'deleted']
  - constraint: fk(server_id) references servers(id) on delete cascade
  - constraint: unique(server_id, topic)
  - constraint: topic != ''
- `cached_messages.json` — Locally cached notification messages ingested from upstream ntfy topics, used to serve ntfy_me_fetch and enable search by content/title/tags/priority. (36 rows; fields: ['id', 'server_id', 'subscription_id', 'topic', 'upstream_event_id', 'upstream_time', 'title', 'message', 'priority', 'tags', 'click', 'icon', 'attachment', 'status', 'received_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'archived', 'deleted']
  - constraint: fk(server_id) references servers(id) on delete cascade
  - constraint: fk(subscription_id) references topic_subscriptions(id) on delete cascade
  - constraint: priority is null or (priority >= 1 and priority <= 5)
  - constraint: unique(subscription_id, upstream_event_id) where upstream_event_id is not null
- `ingest_runs.json` — Operational tracking for polling/stream ingest cycles per subscription (used for reliability, retry/backoff, and diagnosing ntfy fetch issues). (30 rows; fields: ['id', 'server_id', 'subscription_id', 'started_at', 'finished_at', 'status', 'messages_ingested', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(server_id) references servers(id) on delete cascade
  - constraint: fk(subscription_id) references topic_subscriptions(id) on delete cascade
  - constraint: messages_ingested >= 0

## Business rules enforced by the tools

- Tool ntfy_me must create exactly one servers row if no active server exists; if an active server already exists, it must be idempotent and return that existing server without creating duplicates (enforced by unique(display_name) and/or deployment-config fingerprint in implementation).
- Tool ntfy_me must set servers.status to active only after at least one topic_subscriptions row is created in status=active (or explicitly leave the server paused/degraded if subscription setup fails).
- Tool ntfy_me_fetch must return cached_messages for the active server only (servers.status='active') and must not return rows where cached_messages.status='deleted'.
- When ingesting from upstream ntfy, the system must upsert/deduplicate messages by (subscription_id, upstream_event_id) when upstream_event_id is present; otherwise it must insert a new cached_messages row.
- A topic_subscriptions row cannot be active unless its parent servers row is active or degraded; attempting to activate a subscription for a paused/deleted server must be rejected.
- On delete of a server (servers.status -> deleted), all topic_subscriptions and cached_messages rows must be deleted or marked deleted via cascading FK behavior and/or status transitions; fetch must then return an empty set.
- Retention/quota: for each subscription, cached_messages should be capped (e.g., max 10,000 rows); when exceeded, the oldest visible messages must be archived or deleted to stay within limits.