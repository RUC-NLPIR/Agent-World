# HarborLink Integration Router

HarborLink Integration Router is a configuration and routing service for managing external integrations and sending notifications to them for operational communication.

## Datastore

### `integrations.json` — list of 10 records
Holds the catalog of available third-party integrations (including their type, webhook endpoint, and whether they are enabled) so the service can route notifications through the appropriate destination.

- `integration_id` — string
- `name` — string
- `type` — string — one of alerting, chat, errors, issue-tracker, monitoring, status, vcs
- `enabled` — boolean
- `webhook` — string

### `notifications.json` — list of 60 records
Holds notification routing entries associated with integrations so the service can record which messages are sent (or intended to be sent) via which channel and severity level.

- `notification_id` — string
- `integration_id` — string
- `channel` — string
- `level` — string — one of critical, info, warning

### `teams.json` — list of 5 records
Holds team definitions and member lists so the service can associate operational notifications and integration usage with the responsible groups.

- `team_id` — string — one of team-1, team-2, team-3, team-4, team-5
- `name` — string
- `members` — array
