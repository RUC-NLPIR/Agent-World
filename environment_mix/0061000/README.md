# ChronaSchedule Hub

ChronaSchedule Hub is a calendar service for creating, listing, searching, and managing scheduled events across multiple named calendars.

## Datastore

### `calendars.json` — single document
Stores the service's named calendars (team_qc, procurement, manufacturing, management, suppliers) as arrays of event records so the service can retrieve, add, search, and delete events by calendar.

- `team_qc` — array
  each record in `team_qc` has:
  - `uid` — string
  - `summary` — string
  - `dtstart` — string
  - `dtend` — string
  - `description` — string
  - `location` — string
  - `attendees` — array
  - `organizer` — string
  - `recurrence` — string
  - `status` — string
- `procurement` — array
  each record in `procurement` has:
  - `uid` — string
  - `summary` — string
  - `dtstart` — string
  - `dtend` — string
  - `description` — string
  - `location` — string
  - `attendees` — array
  - `organizer` — string
  - `recurrence` — string
- `manufacturing` — array
  each record in `manufacturing` has:
  - `uid` — string
  - `summary` — string
  - `dtstart` — string
  - `dtend` — string
  - `description` — string
  - `location` — string
  - `attendees` — array
  - `organizer` — string
  - `recurrence` — string
- `management` — array
  each record in `management` has:
  - `uid` — string — one of evt-4001, evt-4002, evt-4003, evt-4004, evt-4005, evt-4006, evt-4007
  - `summary` — string
  - `dtstart` — string
  - `dtend` — string
  - `description` — string
  - `location` — string
  - `attendees` — array
  - `organizer` — string
  - `status` — string
- `suppliers` — array
  each record in `suppliers` has:
  - `uid` — string — one of evt-5001, evt-5002, evt-5003, evt-5004, evt-5005
  - `summary` — string
  - `dtstart` — string
  - `dtend` — string
  - `description` — string
  - `location` — string — one of PartsCo Facility, Room B, Zoom-supplier
  - `attendees` — array
  - `organizer` — string
