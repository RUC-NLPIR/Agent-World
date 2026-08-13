# Game Trends — local MCP environment

This backend stores periodically refreshed snapshots of trending/top-selling/most-played game lists from Steam and Epic, plus normalized game catalog entries used to de-duplicate titles across sources. It also stores ingestion job runs and API health check results so the service can report freshness and operational status while serving read-only endpoints.

Repository: https://github.com/halismertkir/game-trends-mcp
Homepage: https://smithery.ai/server/@halismertkir/game-trends-mcp

## Datastore

- `games.json` — Normalized game catalog used across platforms to de-duplicate and attach metadata to items appearing in trend lists. (18 rows; fields: ['id', 'canonical_title', 'slug', 'primary_platform', 'steam_app_id', 'epic_offer_id', 'header_image_url', 'store_url', 'status', 'merged_into_game_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'disabled']
  - constraint: unique(slug)
  - constraint: unique(steam_app_id) where steam_app_id is not null
  - constraint: unique(epic_offer_id) where epic_offer_id is not null
  - constraint: steam_app_id is null or steam_app_id > 0
- `trend_snapshots.json` — A point-in-time snapshot of a platform list (e.g., Steam trending, Steam top sellers, Steam most played, Epic trending, Epic free games). Used to serve read endpoints with 'live' but cacheable data. (16 rows; fields: ['id', 'platform', 'list_type', 'source', 'captured_at', 'expires_at', 'status', 'error_message', 'upstream_etag', 'upstream_request_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['capturing', 'ready', 'stale', 'failed']
  - constraint: platform = 'steam' implies list_type in ('steam_trending','steam_top_sellers','steam_most_played')
  - constraint: platform = 'epic' implies list_type in ('epic_free_games','epic_trending')
  - constraint: status = 'failed' implies error_message is not null
  - constraint: captured_at <= updated_at
- `trend_snapshot_items.json` — Items within a snapshot, ordered and containing list-specific metrics (rank, price, players, promotion window). (18 rows; fields: ['id', 'snapshot_id', 'game_id', 'rank', 'platform_game_key', 'title_override', 'price_amount', 'price_currency', 'discount_percent', 'is_free', 'promo_starts_at', 'promo_ends_at', 'current_players', 'peak_players_24h', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suppressed']
  - constraint: foreign key(snapshot_id) references trend_snapshots(id) on delete cascade
  - constraint: foreign key(game_id) references games(id)
  - constraint: unique(snapshot_id, rank)
  - constraint: rank >= 1
- `ingestion_runs.json` — Tracks background fetch/parse runs that populate snapshots from upstream sources and supports operational debugging and freshness checks. (18 rows; fields: ['id', 'platform', 'list_type', 'status', 'started_at', 'finished_at', 'snapshot_id', 'items_fetched', 'http_requests', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: status in ('succeeded','failed','cancelled') implies finished_at is not null
  - constraint: status = 'running' implies started_at is not null
  - constraint: items_fetched is null or items_fetched >= 0
  - constraint: http_requests is null or http_requests >= 0
- `health_checks.json` — Stores periodic health probe results and derived API health status served by get_api_health. (18 rows; fields: ['id', 'status', 'checked_at', 'steam_ok', 'epic_ok', 'last_successful_snapshot_at', 'details', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'degraded', 'down']
  - constraint: checked_at <= updated_at
  - constraint: status = 'ok' implies steam_ok = true and epic_ok = true

## Business rules enforced by the tools

- Each read tool returns data from the latest trend_snapshots row with status='ready' for its (platform, list_type), preferring captured_at DESC and excluding rows where expires_at is not null and expires_at <= now().
- get_steam_trending_games maps to trend_snapshots(platform='steam', list_type='steam_trending') joined to trend_snapshot_items ordered by rank asc.
- get_steam_top_sellers maps to trend_snapshots(platform='steam', list_type='steam_top_sellers') joined to trend_snapshot_items ordered by rank asc; items may include price_amount/discount_percent when available.
- get_steam_most_played maps to trend_snapshots(platform='steam', list_type='steam_most_played', source in ('steamcharts','multi')) joined to trend_snapshot_items ordered by rank asc; items should include current_players when present.
- get_epic_free_games maps to trend_snapshots(platform='epic', list_type='epic_free_games') joined to trend_snapshot_items ordered by rank asc; items with is_free=true should include promo window when known.
- get_epic_trending_games maps to trend_snapshots(platform='epic', list_type='epic_trending') joined to trend_snapshot_items ordered by rank asc.
- get_all_trending_games returns a composite payload built from the latest ready snapshot for each list_type; it must not mix items from different snapshots of the same list_type.
- Only one 'latest' ready snapshot per (platform, list_type) should be considered current; when a new snapshot becomes ready, prior ready snapshots for the same (platform, list_type) must be transitioned to status='stale'.
- Ingestion creates an ingestion_runs row in status='queued' -> 'running' -> terminal; on success it must create a trend_snapshots row (capturing->ready) and associated trend_snapshot_items within a single transaction.
- A trend_snapshot cannot transition to status='ready' unless it has at least 1 trend_snapshot_items row.
- get_api_health returns the most recent health_checks row by checked_at desc; if none exists, the API reports status='degraded' with details indicating 'no_health_data'.
- Health status derivation: if both steam_ok and epic_ok are true and last_successful_snapshot_at is within the freshness window (e.g., 30 minutes), status='ok'; otherwise status='degraded' unless both dependencies are failing, in which case status='down'.