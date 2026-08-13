# Formula 1 Schedule — local MCP environment

This backend stores Formula 1 season data keyed by year: the race calendar (events and sessions), constructors/teams, drivers, and the computed outcomes (race results and season standings). The main workflow is ingesting/refreshing a season from an upstream provider into normalized tables, then serving read-only API tools that query by year.

Repository: https://github.com/hydavinci/formula-1-schedule.git
Homepage: https://smithery.ai/server/@hydavinci/formula-1-schedule

## Datastore

- `seasons.json` — A Formula 1 season keyed by year. Acts as the parent for calendar, standings, and results data and tracks ingestion/refresh status. (18 rows; fields: ['id', 'year', 'status', 'source', 'source_revision', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'active', 'refreshing', 'archived', 'failed']
  - constraint: unique(year)
  - constraint: year between 1950 and 2100
  - constraint: source in ('ergast','fastf1','official_api','other')
- `events.json` — Calendar events for a season, including race weekend metadata and session schedule. Serves fetch_f1_calendar(year). (20 rows; fields: ['id', 'season_id', 'round', 'race_name', 'circuit_name', 'circuit_city', 'circuit_country', 'circuit_lat', 'circuit_lng', 'timezone', 'race_start_at', 'qualifying_at', 'sprint_at', 'fp1_at', 'fp2_at', 'fp3_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['scheduled', 'completed', 'cancelled']
  - constraint: foreign key (season_id) references seasons(id) on delete cascade
  - constraint: unique(season_id, round)
  - constraint: round >= 1
  - constraint: circuit_lat between -90 and 90 when not null
- `constructors.json` — Constructors/teams participating in a season. Used by team standings and to link results entries. (18 rows; fields: ['id', 'season_id', 'constructor_ref', 'name', 'nationality', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key (season_id) references seasons(id) on delete cascade
  - constraint: unique(season_id, constructor_ref)
  - constraint: unique(season_id, name)
- `drivers.json` — Drivers participating in a season. Used by driver standings and to link results entries. (18 rows; fields: ['id', 'season_id', 'driver_ref', 'code', 'permanent_number', 'given_name', 'family_name', 'date_of_birth', 'nationality', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key (season_id) references seasons(id) on delete cascade
  - constraint: unique(season_id, driver_ref)
  - constraint: code length = 3 when not null
  - constraint: permanent_number between 1 and 99 when not null
- `race_classifications.json` — Per-race classified results for each driver, plus season aggregate standings snapshots for drivers and constructors. Serves fetch_f1_race_results(year), fetch_f1_driver_standings(year), and fetch_f1_team_standings(year). (18 rows; fields: ['id', 'season_id', 'event_id', 'kind', 'driver_id', 'constructor_id', 'position', 'position_text', 'points', 'grid', 'laps', 'time_ms', 'status_text', 'wins', 'standing_round', 'data_status', 'created_at', 'updated_at'])
  - lifecycle `data_status`: ['provisional', 'official', 'amended']
  - constraint: foreign key (season_id) references seasons(id) on delete cascade
  - constraint: foreign key (event_id) references events(id) on delete cascade
  - constraint: foreign key (driver_id) references drivers(id) on delete restrict
  - constraint: foreign key (constructor_id) references constructors(id) on delete restrict

## Business rules enforced by the tools

- Tool parameter year (string) must be parseable to an integer; reject values outside [1950, 2100].
- fetch_f1_calendar(year) reads seasons by year and returns all events where events.season_id matches, ordered by round ascending.
- fetch_f1_race_results(year) returns all race_classifications rows where kind='race_result' for the matching season, joined to events/drivers/constructors; results are grouped by event round and ordered by position (nulls last).
- fetch_f1_driver_standings(year) returns the latest driver standings snapshot for the matching season: choose rows where kind='driver_standing' and standing_round is max for that season (or standing_round is null as 'latest' if present), ordered by position.
- fetch_f1_team_standings(year) returns the latest constructor standings snapshot for the matching season: choose rows where kind='constructor_standing' and standing_round is max for that season (or standing_round is null as 'latest' if present), ordered by position.
- A season in status 'failed' must not be served unless a stale-but-active prior snapshot exists (implementations typically serve the last 'active' data or return an upstream error).
- Ingestion/refresh must be atomic per season: during seasons.status='refreshing', writes may upsert events/drivers/constructors/classifications, but reads should continue to use the most recent official/amended rows (data_status != 'provisional') when available.
- When events.status transitions to 'completed', race_result rows for that event must exist for at least one driver; if not, the completion transition is invalid.