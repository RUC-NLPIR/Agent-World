# Amadeus MCP Server — local MCP environment

This backend stores authenticated access to the Amadeus flight shopping API through an MCP server, tracking API keys, each flight-offer search request, the resulting offers returned by Amadeus, and usage/accounting for rate limits and cost control. Main workflows are: issue/rotate API credentials, perform flight offer searches, persist results for later inspection, and enforce quotas per API key.

Repository: https://github.com/donghyun-chae/mcp-amadeus
Homepage: https://smithery.ai/server/@donghyun-chae/mcp-amadeus

## Datastore

- `workspaces.json` — Tenant/workspace owning API keys and all searches executed through this MCP server instance. (12 rows; fields: ['id', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: name != ''
- `api_keys.json` — API credentials/config used by the MCP server to call Amadeus (client_id/client_secret), plus per-key quotas and rotation state. (12 rows; fields: ['id', 'workspace_id', 'name', 'amadeus_environment', 'client_id', 'client_secret_ciphertext', 'status', 'daily_request_limit', 'daily_request_count', 'daily_window_start_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: daily_request_limit >= 0
  - constraint: daily_request_count >= 0
  - constraint: daily_request_count <= daily_request_limit OR daily_request_limit = 0
- `flight_offer_searches.json` — A single invocation of the search_flight_offers tool. Because the tool schema has no parameters, this table captures server-derived context, default search configuration, and the Amadeus request/response payloads for auditing and replay. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'trigger_source', 'default_search_config', 'amadeus_request', 'amadeus_response', 'http_status_code', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: http_status_code BETWEEN 100 AND 599 OR http_status_code IS NULL
  - constraint: started_at IS NULL OR created_at <= started_at
  - constraint: finished_at IS NULL OR started_at <= finished_at
  - constraint: api_key_id REFERENCES api_keys(id) ON DELETE RESTRICT
- `flight_offers.json` — Normalized flight offers extracted from an Amadeus flight offer search response, enabling inspection, caching and downstream processing. (19 rows; fields: ['id', 'search_id', 'amadeus_offer_id', 'source', 'currency', 'total_price', 'base_price', 'taxes_price', 'itineraries', 'validating_airline_codes', 'traveler_pricings', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'discarded']
  - constraint: unique(search_id, amadeus_offer_id)
  - constraint: total_price >= 0
  - constraint: base_price IS NULL OR base_price >= 0
  - constraint: taxes_price IS NULL OR taxes_price >= 0
- `usage_events.json` — Append-only usage ledger for quota enforcement and operational analytics (per call to search_flight_offers). (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'search_id', 'event_type', 'request_units', 'http_status_code', 'occurred_at', 'created_at'])
  - lifecycle `event_type`: ['amadeus_request', 'amadeus_response', 'amadeus_error']
  - constraint: request_units >= 0
  - constraint: http_status_code BETWEEN 100 AND 599 OR http_status_code IS NULL
  - constraint: workspace_id REFERENCES workspaces(id) ON DELETE CASCADE
  - constraint: api_key_id REFERENCES api_keys(id) ON DELETE RESTRICT

## Business rules enforced by the tools

- Calling search_flight_offers MUST create a flight_offer_searches row with trigger_source='mcp_tool_call' and status transitioning queued -> running -> (succeeded|failed).
- Because the tool has no parameters, the server MUST populate flight_offer_searches.default_search_config from workspace-level or environment defaults; it MUST be non-empty JSON.
- A flight_offer_searches row MUST reference an api_keys row in status='active'; otherwise the search must fail with error_code='AUTH_FAILED' and status='failed'.
- Before executing an Amadeus request, the system MUST enforce api_keys.daily_request_limit: if limit>0 and daily_request_count + 1 > daily_request_limit, the search MUST fail with error_code='RATE_LIMITED'.
- On each successful Amadeus request attempt (even if the response is an error), the system MUST append a usage_events row with event_type='amadeus_request' and request_units=1 and increment api_keys.daily_request_count atomically.
- If the Amadeus call succeeds and returns offers, the system MUST upsert flight_offers for the search with unique(search_id, amadeus_offer_id) and set offer status='active'.
- Deleting a workspace MUST cascade delete flight_offer_searches, flight_offers, and usage_events, but MUST NOT delete api_keys if used elsewhere; api_keys are restricted by FK and should be revoked/disabled first.
- flight_offer_searches.amadeus_request and amadeus_response MUST be stored with secrets removed (no client_secret, no authorization bearer tokens).