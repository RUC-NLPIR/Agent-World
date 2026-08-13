# OpenDota API Server — local MCP environment

This backend stores normalized OpenDota-derived data for Dota 2 entities (players, matches, heroes, and teams) and the relationships between them (match participants, player-hero aggregates). Primary workflows are reading player/match/team/hero views and serving limited search over player identities, with lightweight caching/lifecycle states for ingested snapshots.

Repository: https://github.com/lieyanqzu/opendota-mcp-server
Homepage: https://smithery.ai/server/@lieyanqzu/opendota-mcp-server

## Datastore

- `players.json` — Steam/OpenDota player identity and cached profile/stat summary used by player endpoints and search. (18 rows; fields: ['id', 'steam32_account_id', 'persona_name', 'avatar_url', 'profile_url', 'country_code', 'rank_tier', 'leaderboard_rank', 'is_pro', 'pro_team_id', 'pro_name', 'last_match_id_seen', 'profile_status', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `profile_status`: ['active', 'stale', 'disabled', 'deleted']
  - constraint: unique(steam32_account_id)
  - constraint: steam32_account_id > 0
  - constraint: rank_tier is null or (rank_tier >= 0 and rank_tier <= 100)
  - constraint: leaderboard_rank is null or leaderboard_rank > 0
- `teams.json` — Professional teams metadata keyed by the OpenDota team_id (external_team_id). (18 rows; fields: ['id', 'external_team_id', 'name', 'tag', 'logo_url', 'country_code', 'rating', 'status', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deleted']
  - constraint: unique(external_team_id)
  - constraint: external_team_id > 0
  - constraint: name <> ''
- `heroes.json` — Dota 2 hero reference data and cached global hero statistics (win rates by bracket, etc.). (18 rows; fields: ['id', 'external_hero_id', 'name', 'localized_name', 'primary_attr', 'attack_type', 'roles', 'img_url', 'icon_url', 'legs', 'global_stats', 'stats_status', 'last_stats_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `stats_status`: ['fresh', 'stale', 'disabled']
  - constraint: unique(external_hero_id)
  - constraint: external_hero_id > 0
  - constraint: name <> ''
  - constraint: localized_name <> ''
- `matches.json` — Match headers and cached detailed match data for public and pro matches; used to serve match detail and lists. (18 rows; fields: ['id', 'match_id', 'start_time', 'duration_seconds', 'radiant_win', 'radiant_score', 'dire_score', 'lobby_type', 'game_mode', 'region', 'is_pro', 'league_id', 'series_id', 'radiant_team_id', 'dire_team_id', 'match_status', 'raw_payload', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `match_status`: ['header_only', 'parsed', 'failed', 'deleted']
  - constraint: unique(match_id)
  - constraint: match_id > 0
  - constraint: duration_seconds is null or duration_seconds >= 0
  - constraint: radiant_score is null or radiant_score >= 0
- `match_players.json` — Join table of match participants (10 players per match), including hero picks and per-player stats; powers match heroes and many player endpoints (recent matches, peers, hero rankings, win/loss, totals). (19 rows; fields: ['id', 'match_id', 'player_account_id', 'slot', 'is_radiant', 'hero_id', 'won', 'kills', 'deaths', 'assists', 'gold_per_min', 'xp_per_min', 'last_hits', 'denies', 'hero_damage', 'hero_healing', 'tower_damage', 'leaver_status', 'party_size', 'additional_stats', 'row_status', 'created_at', 'updated_at'])
  - lifecycle `row_status`: ['active', 'deleted']
  - constraint: unique(match_id, slot)
  - constraint: match_id exists matches.match_id
  - constraint: hero_id exists heroes.external_hero_id
  - constraint: player_account_id is null or exists players.steam32_account_id
- `player_hero_aggregates.json` — Precomputed per-player-per-hero aggregates and derived ranking fields to serve 'most played heroes' and 'hero rankings' efficiently. (18 rows; fields: ['id', 'player_account_id', 'hero_id', 'match_count', 'win_count', 'with_games', 'with_wins', 'avg_kda', 'ranking_score', 'aggregate_status', 'computed_at', 'created_at', 'updated_at'])
  - lifecycle `aggregate_status`: ['current', 'recomputing', 'stale']
  - constraint: unique(player_account_id, hero_id)
  - constraint: player_account_id exists players.steam32_account_id
  - constraint: hero_id exists heroes.external_hero_id
  - constraint: match_count >= 0

## Business rules enforced by the tools

- get_player_by_id(account_id) must resolve players.steam32_account_id = account_id; if missing, the service may create a players row with profile_status='stale' and minimal identity fields before returning/refreshing.
- get_player_recent_matches(account_id, limit) returns matches joined through match_players for that player_account_id ordered by matches.start_time desc (or match_id desc if start_time null) with limit constrained to 1 <= limit <= 100.
- get_match_data(match_id) reads matches.match_id = match_id; if match_status != 'parsed', the service may return header_only data plus raw_payload when available, but must not create duplicate matches due to unique(match_id).
- get_player_win_loss(account_id) computes wins/losses from match_players.won grouped for player_account_id where won is not null; wins=count(won=true), losses=count(won=false).
- get_player_heroes(account_id, limit) reads player_hero_aggregates filtered by player_account_id ordered by match_count desc (or win_rate desc as tie-break) with limit constrained to 1 <= limit <= 100.
- get_hero_stats(hero_id) when hero_id is null returns heroes.global_stats for all heroes with stats_status in ('fresh','stale'); when hero_id is provided it must match heroes.external_hero_id exactly.
- search_player(query) searches players.persona_name and players.pro_name using a case-insensitive match; results must exclude players.profile_status in ('deleted') and must cap returned rows to a safe server-side maximum (e.g., 50).
- get_pro_players(limit) returns players where is_pro=true ordered by leaderboard_rank asc nulls last, constrained to 1 <= limit <= 100.
- get_pro_matches(limit) returns matches where is_pro=true ordered by start_time desc with limit constrained to 1 <= limit <= 100.
- get_player_peers(account_id, limit) computes peers by finding other match_players rows in the same matches as the subject player (same match_id) where other.player_account_id is not null and != account_id, aggregating games and wins; limit constrained to 1 <= limit <= 100.
- get_heroes() returns all heroes where heroes.id exists, ordered by external_hero_id asc; heroes.stats_status does not affect inclusion for basic list.
- get_player_totals(account_id) derives totals by summing relevant numeric fields across match_players for player_account_id (kills/deaths/assists/gpm/xpm/etc.) ignoring nulls.
- get_player_rankings(account_id) returns player_hero_aggregates filtered by player_account_id ordered by ranking_score desc nulls last; if ranking_score is null, fallback to match_count desc.
- get_player_wordcloud(account_id) is served from players-derived cached blobs when available; if not persisted separately, the service must read it from players.profile/raw upstream and store in players (e.g., a field within players not modeled here) OR embed it in players via an extension to players.additional_profile object; implementation must not require a new collection for correctness.
- get_team_info(team_id) reads teams.external_team_id = team_id; if missing, may create a teams row with status='inactive' and last_refreshed_at null, then refresh asynchronously.
- get_public_matches(limit) returns matches where is_pro=false ordered by start_time desc with limit constrained to 1 <= limit <= 100.
- get_match_heroes(match_id) returns match_players filtered by match_id projecting hero_id joined to heroes for names; must return at most 10 rows for a fully populated match and enforce unique(match_id, slot).