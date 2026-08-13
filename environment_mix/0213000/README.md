# Keystone Calendar Directory

Keystone Calendar Directory is a simple calendar directory service for looking up users and querying scheduled events and holidays by date, attendee, and title.

## Datastore

### `users.json` — list of 50 records
Holds user profiles (identity, email, display name, and timezone) so the service can resolve and search calendars by person.

- `id` — string
- `email` — string
- `name` — string
- `timezone` — string

### `holidays.json` — list of 18 records
Holds holiday entries with times and type so the service can surface non-working or observance dates alongside regular events.

- `event_id` — string
- `title` — string
- `start_time` — string
- `end_time` — string
- `attendees` — array
- `location` — null — nullable
- `type` — string — one of Federal Holiday, Observance

### `events.json` — list of 180 records
Holds calendar events with times, attendees, and locations so the service can list, search, and retrieve scheduled meetings.

- `event_id` — string
- `title` — string
- `start_time` — string
- `end_time` — string
- `attendees` — array
- `location` — string
