# National Parks Information Server — local MCP environment

This backend stores normalized National Park Service-style content: parks, their public details, and related operational information such as alerts, visitor centers, campgrounds, and events. Primary workflows are read-heavy lookups and listings (find parks, then fetch park-specific related resources) with periodic upstream syncs that update park data and time-sensitive items like alerts and events.

Repository: https://github.com/geobio/mcp-server-nationalparks
Homepage: https://smithery.ai/server/@geobio/mcp-server-nationalparks

## Datastore

- `parks.json` — Core national park units and their canonical public-facing details. This is the anchor entity for all other resources. (21 rows; fields: ['id', 'park_code', 'full_name', 'name', 'designation', 'description', 'states', 'latitude', 'longitude', 'directions_info', 'directions_url', 'url', 'weather_info', 'images', 'contacts', 'entrance_fees', 'operating_hours', 'status', 'source', 'source_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deleted']
  - constraint: unique(park_code)
  - constraint: full_name != ''
  - constraint: name != ''
  - constraint: states length >= 1
- `alerts.json` — Operational alerts for parks (closures, hazards, information). Typically time-sensitive and frequently refreshed. (20 rows; fields: ['id', 'park_id', 'source_alert_id', 'category', 'title', 'description', 'url', 'effective_start', 'effective_end', 'severity', 'status', 'source_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'retracted']
  - constraint: foreign key (park_id) references parks(id) on delete cascade
  - constraint: unique(park_id, source_alert_id) where source_alert_id is not null
  - constraint: title != ''
  - constraint: effective_end is null OR effective_start is null OR effective_end >= effective_start
- `visitor_centers.json` — Visitor centers for parks including location and operating hour data. (21 rows; fields: ['id', 'park_id', 'source_facility_id', 'name', 'description', 'latitude', 'longitude', 'phone', 'email', 'url', 'operating_hours', 'status', 'source_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'seasonal', 'closed', 'inactive']
  - constraint: foreign key (park_id) references parks(id) on delete cascade
  - constraint: unique(park_id, source_facility_id) where source_facility_id is not null
  - constraint: name != ''
  - constraint: latitude is null OR (latitude >= -90 AND latitude <= 90)
- `campgrounds.json` — Campgrounds for parks including amenities, fees, and seasonal/operational details. (19 rows; fields: ['id', 'park_id', 'source_campground_id', 'name', 'description', 'latitude', 'longitude', 'reservation_url', 'fees', 'amenities', 'campsites', 'operating_hours', 'status', 'source_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'seasonal', 'closed', 'inactive']
  - constraint: foreign key (park_id) references parks(id) on delete cascade
  - constraint: unique(park_id, source_campground_id) where source_campground_id is not null
  - constraint: name != ''
  - constraint: latitude is null OR (latitude >= -90 AND latitude <= 90)
- `events.json` — Public events at parks (talks, ranger programs, tours). Often filtered by date range and park. (21 rows; fields: ['id', 'park_id', 'source_event_id', 'title', 'description', 'category', 'location', 'start_at', 'end_at', 'is_all_day', 'url', 'fee_info', 'status', 'source_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['scheduled', 'cancelled', 'completed', 'inactive']
  - constraint: foreign key (park_id) references parks(id) on delete cascade
  - constraint: unique(park_id, source_event_id) where source_event_id is not null
  - constraint: title != ''
  - constraint: end_at is null OR end_at >= start_at

## Business rules enforced by the tools

- findParks returns parks where parks.status = 'active', ordered by full_name, and may be cached; no tool parameters map to filters because the tool surface defines none.
- getParkDetails returns a single park record; if the request does not specify an identifier, the implementation must select a deterministic default (e.g., first active park by full_name) and must not return parks.status = 'deleted'.
- getAlerts returns alerts joined to parks where parks.status = 'active' and alerts.status = 'active'; expired/retracted alerts must not be returned unless the server is in an internal/debug mode.
- getVisitorCenters returns visitor centers joined to parks where parks.status = 'active' and visitor_centers.status in ('open','seasonal','closed'); records marked 'inactive' must be excluded from public responses.
- getCampgrounds returns campgrounds joined to parks where parks.status = 'active' and campgrounds.status in ('open','seasonal','closed'); records marked 'inactive' must be excluded from public responses.
- getEvents returns events joined to parks where parks.status = 'active' and events.status in ('scheduled'); events with start_at in the past may be returned only if still 'scheduled' (e.g., multi-day ongoing) or if the service explicitly chooses to include 'completed'.
- All child entities (alerts, visitor_centers, campgrounds, events) require a valid park_id; inserts/updates must fail if the referenced park does not exist.
- Upstream sync is idempotent: when source_*_id is present, upserts must enforce unique(park_id, source_*_id) and update source_updated_at/updated_at rather than creating duplicates.
- Status transitions must follow the declared lifecycle transitions; direct transitions not listed are rejected.
- Latitude/longitude validation is enforced on write for parks, visitor_centers, and campgrounds; invalid coordinates must be rejected.