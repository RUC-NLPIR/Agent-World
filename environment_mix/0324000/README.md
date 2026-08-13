# SkyLattice Weather Hub

SkyLattice Weather Hub is a weather data service that serves current conditions, forecasts, alerts, and nearby station information for U.S. locations.

## Datastore

### `weather.json` — single document
Holds the service’s weather station directory plus per-location weather snapshots (current, daily, hourly, and alerts) so the service can respond to location-based weather queries and station lookups.

- `stations` — array
  each record in `stations` has:
  - `id` — string
  - `name` — string
  - `lat` — number
  - `lng` — number
- `by_location` — object
  each record in `by_location` has:
  - `place` — string
  - `timezone` — string — one of America/Chicago, America/Denver, America/Los_Angeles, America/New_York, America/Phoenix
  - `current` — object
    each record in `current` has:
    - `temperature_f` — integer
    - `conditions` — string — one of Cloudy, Partly Cloudy, Sunny
    - `humidity` — integer
    - `wind_mph` — integer
    - `wind_dir` — string — one of E, NE, NW, S, SW, W
  - `daily` — array
    each record in `daily` has:
    - `date` — string — one of 2026-06-24, 2026-06-25, 2026-06-26, 2026-06-27, 2026-06-28, 2026-06-29, 2026-06-30
    - `high_f` — integer
    - `low_f` — integer
    - `summary` — string — one of Cloudy, Excessive Heat, Heat Advisory, Partly Cloudy, Showers, Sunny, Thunderstorms
  - `hourly` — array
    each record in `hourly` has:
    - `time` — string
    - `temperature_f` — integer
    - `conditions` — string — one of Clear, Cloudy, Fog, Partly Cloudy, Sunny
  - `alerts` — array
    each record in `alerts` has:
    - `event` — string
    - `severity` — string — one of minor, moderate, severe
    - `headline` — string
    - `areas` — string
- `default` — object
  each record in `default` has:
  - `temperature_f` — integer
  - `conditions` — string
  - `humidity` — integer
  - `wind_mph` — integer
  - `wind_dir` — string
