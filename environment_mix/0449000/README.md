# OP.GG — local MCP environment

This backend stores OP.GG-style aggregated game intelligence across multiple titles (LoL, TFT, Valorant, and LoL esports): static catalogs (champions/items/maps/agents), periodically computed meta snapshots (tiers, builds, leaderboards, standings), and player identity + match history caches keyed by Riot identifiers. Main workflows are: (1) scheduled ingestion from upstream game data sources to produce daily/patch meta snapshots; (2) on-demand player refresh jobs ("renewal") that update a cached player profile and match history; (3) read APIs that serve the latest applicable snapshot by region/mode/language or return cached player data.

Repository: https://github.com/opgginc/opgg-mcp
Homepage: https://smithery.ai/server/@opgginc/opgg-mcp

## Datastore

- `game_catalog.json` — Canonical cross-game catalog entities used by all tools: LoL champions/skins, TFT champions/items, Valorant maps/agents, and esports leagues. Stores localized names where needed and stable external IDs used for lookups. (17 rows; fields: ['id', 'game', 'entity_type', 'external_key', 'display_name_default', 'localized_names', 'metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(game, entity_type, external_key)
  - constraint: external_key <> ''
  - constraint: display_name_default <> ''
- `meta_snapshots.json` — Versioned computed datasets (snapshots) for LoL/TFT/Valorant/esports that power most read endpoints. Each snapshot records the query dimensions (region/mode/position/lang/league/map) and stores the resulting payload (builds, tiers, leaderboards, standings, meta stats). (19 rows; fields: ['id', 'game', 'snapshot_type', 'region', 'lang', 'game_mode', 'position', 'champion_external_key', 'tft_champion_external_key', 'tft_item_external_key', 'valorant_map_external_key', 'esports_league_short_name', 'format', 'source_patch', 'effective_from', 'effective_to', 'payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['building', 'active', 'superseded', 'failed']
  - constraint: effective_from <= coalesce(effective_to, effective_from)
  - constraint: For snapshot_type='LOL_CHAMPION_ANALYSIS': game='LOL' AND game_mode IS NOT NULL AND position IS NOT NULL AND lang IS NOT NULL AND champion_external_key IS NOT NULL
  - constraint: For snapshot_type='LOL_CHAMPION_LEADERBOARD': region IS NOT NULL AND champion_external_key IS NOT NULL
  - constraint: For snapshot_type='LOL_CHAMPION_META_DATA': champion_external_key IS NOT NULL AND lang IS NOT NULL
- `players.json` — Cached player identities across LoL/TFT/Valorant keyed by Riot ID (game_name + tag_line) and, when available, puuid. Used to serve summoner search, match history, and TFT playstyle comments; renewed via explicit renewal jobs. (18 rows; fields: ['id', 'product', 'game_name', 'tag_line', 'normalized_riot_id', 'region', 'puuid', 'profile_payload', 'last_renewed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'not_found', 'disabled']
  - constraint: game_name <> ''
  - constraint: tag_line <> ''
  - constraint: normalized_riot_id <> ''
  - constraint: unique(product, region, normalized_riot_id)
- `player_matches.json` — Cached match history entries per player. Populated during renewal and used by lol-summoner-game-history and valorant-player-match-history. (18 rows; fields: ['id', 'player_id', 'product', 'region', 'external_match_id', 'played_at', 'queue_or_mode', 'summary_payload', 'ingested_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden']
  - constraint: unique(player_id, external_match_id)
  - constraint: played_at <= ingested_at
  - constraint: external_match_id <> ''
  - constraint: FK player_id must exist
- `renewal_jobs.json` — On-demand data refresh jobs triggered by lol-summoner-renewal (and internal refresh flows). Tracks renewals against Riot/OP.GG sources and updates players + player_matches caches. (19 rows; fields: ['id', 'product', 'region', 'game_name', 'tag_line', 'normalized_riot_id', 'player_id', 'requested_by', 'status', 'attempt_count', 'last_error', 'enqueued_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'rate_limited']
  - constraint: attempt_count >= 0
  - constraint: enqueued_at <= coalesce(started_at, enqueued_at)
  - constraint: coalesce(started_at, enqueued_at) <= coalesce(finished_at, coalesce(started_at, enqueued_at))
  - constraint: unique(product, region, normalized_riot_id, enqueued_at)

## Business rules enforced by the tools

- lol-summoner-renewal MUST insert a renewal_jobs row (status='queued'), then execute/dispatch it; on success it MUST upsert players(product='LOL', region, normalized_riot_id) and update players.last_renewed_at, then upsert recent player_matches for that player.
- lol-summoner-search and lol-summoner-game-history MUST read from players/player_matches caches; if players.status='not_found' and last_renewed_at is null or stale, the client should be instructed to run renewal again (the tool contract says renewal first).
- tft-play-style-comment MUST resolve a players row by puuid + region (or create one during ingestion) and MUST reject/return not found when no player with matching (product='TFT', region, puuid) exists.
- All champion/item/map/agent IDs accepted by tools (e.g., 'ANNIE', 'TFT14_Aphelios', Valorant mapId) must correspond to an active game_catalog row; ingestion may temporarily accept unknown external keys but must mark them deprecated/active once validated.
- Meta read tools MUST return the latest meta_snapshots row with status='active' matching the tool dimensions (region/lang/mode/position/champion/map/league/format). If none exists, they may fall back to the most recent 'superseded' snapshot within an allowed staleness window.
- lol-champion-positions-data MUST support format='csv' and format='json_zip'; if format is omitted, it MUST be treated as 'csv' and reflected as such in the meta_snapshots lookup key.
- Only one active snapshot per snapshot_type and dimension set is allowed (enforced by constraints); publishing a new one must atomically set the previous active snapshot to status='superseded' and set its effective_to.
- Region enums are product-specific: LoL/TFT use the LoL-style region list (including SEA where applicable); Valorant leaderboard uses only {AP, BR, EU, KR, LATAM, NA}. Requests outside the allowed enum must be rejected at validation time.
- Deletion is logical: catalog, players, matches, and snapshots are not hard-deleted in normal operations; they transition to deprecated/disabled/hidden/superseded statuses to preserve referential integrity and auditability.