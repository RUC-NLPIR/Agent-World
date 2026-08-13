# Balldontlie Sports Data Server — local MCP environment

This backend stores normalized sports reference data (leagues, teams, players) and event data (games) for NBA/MLB/NFL. The primary workflow is read-only querying of teams/players/games and fetching a single game by id; optionally the system tracks API access for operational monitoring and throttling.

Repository: https://github.com/mikechao/balldontlie-mcp
Homepage: https://smithery.ai/server/@mikechao/balldontlie-mcp

## Datastore

- `leagues.json` — Supported sports leagues (NBA, MLB, NFL) used to partition teams, players, and games. (12 rows; fields: ['id', 'code', 'name', 'sport', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(code)
  - constraint: code in ('NBA','MLB','NFL')
  - constraint: status in ('active','disabled')
- `teams.json` — Teams belonging to a league (used by get_teams and as foreign keys for games and players). (30 rows; fields: ['id', 'league_id', 'external_provider', 'external_team_id', 'abbreviation', 'city', 'name', 'full_name', 'conference', 'division', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'relocated']
  - constraint: foreign key(league_id) references leagues(id) on update cascade on delete restrict
  - constraint: unique(external_provider, external_team_id)
  - constraint: length(abbreviation) <= 5
  - constraint: status in ('active','inactive','relocated')
- `players.json` — Players for NBA/MLB/NFL used by get_players; optionally linked to a current team. (33 rows; fields: ['id', 'league_id', 'external_provider', 'external_player_id', 'first_name', 'last_name', 'display_name', 'position', 'jersey_number', 'height_inches', 'weight_lbs', 'current_team_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'retired']
  - constraint: foreign key(league_id) references leagues(id) on update cascade on delete restrict
  - constraint: foreign key(current_team_id) references teams(id) on update cascade on delete set null
  - constraint: unique(external_provider, external_player_id)
  - constraint: height_inches is null or (height_inches between 36 and 120)
- `games.json` — Games/events for NBA/MLB/NFL used by get_games and get_game. Includes home/away teams and scores when available. (31 rows; fields: ['id', 'league_id', 'external_provider', 'external_game_id', 'season', 'start_time', 'home_team_id', 'away_team_id', 'home_score', 'away_score', 'venue_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['scheduled', 'in_progress', 'final', 'cancelled', 'postponed']
  - constraint: foreign key(league_id) references leagues(id) on update cascade on delete restrict
  - constraint: foreign key(home_team_id) references teams(id) on update cascade on delete restrict
  - constraint: foreign key(away_team_id) references teams(id) on update cascade on delete restrict
  - constraint: home_team_id <> away_team_id
- `api_request_logs.json` — Operational request log to support throttling, debugging, and usage analytics for the read endpoints/tools. (32 rows; fields: ['id', 'request_time', 'tool_name', 'league_code', 'game_id', 'http_status', 'response_ms', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `http_status`: ['200', '400', '404', '429', '500']
  - constraint: tool_name in ('get_teams','get_players','get_games','get_game')
  - constraint: http_status between 100 and 599
  - constraint: response_ms >= 0
  - constraint: league_code is null or league_code in ('NBA','MLB','NFL')

## Business rules enforced by the tools

- get_teams returns teams where teams.status = 'active' and the referenced leagues.status = 'active'.
- get_players returns players where players.status in ('active','inactive','retired') and leagues.status = 'active'; if current_team_id is non-null it must reference a team in the same league_id as the player.
- get_games returns games where leagues.status = 'active' and both home_team_id and away_team_id reference teams in the same league_id as the game.
- get_game must return exactly one game by id; if the id is not found, return a not-found result and record http_status=404 in api_request_logs.
- A game cannot transition to 'final' unless home_score and away_score are both non-null.
- Scores must be non-negative integers; if status is 'scheduled', both scores must be null.
- Upstream uniqueness is enforced: (external_provider, external_team_id) is unique in teams; (external_provider, external_player_id) is unique in players; (external_provider, external_game_id) is unique in games.
- All tool invocations create an api_request_logs row with tool_name, request_time, http_status, and response_ms populated.