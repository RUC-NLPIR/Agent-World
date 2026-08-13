# AtlasRoute Response Vault

AtlasRoute Response Vault is a service that loads and stores sample Google Maps Platform API responses for routing, distances, elevation, geocoding, and place search/details.

## Datastore

### `directions_chicago_santamonica.json` — single document
Holds a Directions-style response with routes, legs, warnings, and an overview polyline for the Chicago-to–Santa Monica drive so the service can retain a concrete routing example.

- `routes` — array
  each record in `routes` has:
  - `summary` — string
  - `legs` — array
    each record in `legs` has:
    - `start_address` — string
    - `end_address` — string
    - `distance` — object
    - `duration` — object
    - `steps` — array
  - `warnings` — array
  - `overview_polyline` — object
    each record in `overview_polyline` has:
    - `points` — string
- `status` — string

### `directions_ny_chicago.json` — single document
Holds a Directions-style response with routes, legs, warnings, and an overview polyline for the New York-to–Chicago drive so the service can retain a concrete routing example.

- `routes` — array
  each record in `routes` has:
  - `summary` — string
  - `legs` — array
    each record in `legs` has:
    - `start_address` — string
    - `end_address` — string
    - `distance` — object
    - `duration` — object
    - `steps` — array
  - `warnings` — array
  - `overview_polyline` — object
    each record in `overview_polyline` has:
    - `points` — string
- `status` — string

### `distance_matrix.json` — single document
Holds a Distance Matrix-style response with origin and destination address lists and per-pair elements so the service can keep a multi-origin/multi-destination distance and duration example.

- `destination_addresses` — array
- `origin_addresses` — array
- `rows` — array
  each record in `rows` has:
  - `elements` — array
    each record in `elements` has:
    - `status` — string
    - `duration` — object
    - `distance` — object
- `status` — string

### `elevation_multi.json` — single document
Holds an Elevation-style response with elevation results for multiple locations so the service can keep a set of representative elevation lookups.

- `results` — array
  each record in `results` has:
  - `elevation` — number
  - `location` — object
    each record in `location` has:
    - `lat` — number
    - `lng` — number
  - `resolution` — number
- `status` — string

### `geocode_examples.json` — single document
Holds a Geocoding-style response with address components, geometry, and place identifiers so the service can keep example forward-geocoding results.

- `results` — array
  each record in `results` has:
  - `address_components` — array
    each record in `address_components` has:
    - `long_name` — string
    - `short_name` — string
    - `types` — array
  - `formatted_address` — string
  - `geometry` — object
    each record in `geometry` has:
    - `lat` — number
    - `lng` — number
    - `northeast` — object
    - `southwest` — object
  - `place_id` — string
  - `types` — array
- `status` — string

### `place_details_eiffel_tower.json` — single document
Holds a Place Details-style response (including result geometry and open_now) so the service can keep a stored details lookup for the Eiffel Tower.

- `html_attributions` — array
- `result` — object
  each record in `result` has:
  - `location` — object
    each record in `location` has:
    - `lat` — number
    - `lng` — number
  - `viewport` — object
    each record in `viewport` has:
    - `lat` — number
    - `lng` — number
  - `open_now` — boolean
- `status` — string

### `place_details_google_sydney.json` — single document
Holds a Place Details-style response (including result geometry and open_now) so the service can keep a stored details lookup for Google Sydney.

- `html_attributions` — array
- `result` — object
  each record in `result` has:
  - `location` — object
    each record in `location` has:
    - `lat` — number
    - `lng` — number
  - `viewport` — object
    each record in `viewport` has:
    - `lat` — number
    - `lng` — number
  - `open_now` — boolean
- `status` — string

### `reverse_geocode_examples.json` — single document
Holds a Reverse Geocoding-style response with formatted addresses, address components, geometry, and place identifiers so the service can keep example coordinate-to-address results.

- `results` — array
  each record in `results` has:
  - `formatted_address` — string
  - `address_components` — array
    each record in `address_components` has:
    - `long_name` — string
    - `short_name` — string
    - `types` — array
  - `geometry` — object
    each record in `geometry` has:
    - `lat` — number
    - `lng` — number
    - `northeast` — object
    - `southwest` — object
  - `place_id` — string
- `status` — string

### `search_places_coffee_ny.json` — single document
Holds a Places Search-style response with candidate places and basic attributes so the service can keep an example search for coffee near Times Square.

- `html_attributions` — array
- `results` — array
  each record in `results` has:
  - `place_id` — string — one of ChIJP3hjYjZnwokRD_EUml6I, ChIJy8e0QZ1nwokRj0KcTI3w, ChIJyY7K5x5nwokR9k6g9bTJ
  - `name` — string
  - `geometry` — object
    each record in `geometry` has:
    - `lat` — number
    - `lng` — number
  - `vicinity` — string
  - `rating` — number
  - `user_ratings_total` — integer
  - `types` — array
- `status` — string

### `search_places_hotels_paris.json` — single document
Holds a Places Search-style response with candidate places and basic attributes so the service can keep an example search for hotels in Paris.

- `html_attributions` — array
- `results` — array
  each record in `results` has:
  - `place_id` — string
  - `name` — string
  - `geometry` — object
    each record in `geometry` has:
    - `lat` — number
    - `lng` — number
  - `vicinity` — string
  - `rating` — number
  - `user_ratings_total` — integer
  - `types` — array
- `status` — string
