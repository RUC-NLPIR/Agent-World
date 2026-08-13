# AeroVale Flight Desk

AeroVale Flight Desk is a flight shopping and reservation service that lets users look up flights and manage bookings tied to user profiles.

## Datastore

### `flights.json` — object of 300 records keyed by identifier
Holds the published flight list plus per-date operational and sales information so the service can search, price, and report availability and day-of-flight status.
Keys look like: HAT001, HAT002, HAT003

- `flight_number` — string
- `origin` — string
- `destination` — string
- `scheduled_departure_time_est` — string
- `scheduled_arrival_time_est` — string
- `dates` — object
  each record in `dates` has:
  - `status` — string — one of available, cancelled, delayed, flying, landed, on time
  - `actual_departure_time_est` — string
  - `actual_arrival_time_est` — string
  - `available_seats` — object
    each record in `available_seats` has:
    - `basic_economy` — integer
    - `economy` — integer
    - `business` — integer
  - `prices` — object
    each record in `prices` has:
    - `basic_economy` — integer
    - `economy` — integer
    - `business` — integer
  - `estimated_departure_time_est` — string
  - `estimated_arrival_time_est` — string

### `reservations.json` — object of 2000 records keyed by identifier
Holds booked itineraries with passenger, flight segment, baggage, insurance, payment history, and creation metadata so the service can retrieve and cancel reservations.
Keys look like: 4WQ150, VAAOXJ, PGAGLM

- `reservation_id` — string
- `user_id` — string — references users.id
- `origin` — string
- `destination` — string
- `flight_type` — string — one of one_way, round_trip
- `cabin` — string — one of basic_economy, business, economy
- `flights` — array
  each record in `flights` has:
  - `origin` — string
  - `destination` — string
  - `flight_number` — string
  - `date` — string
  - `price` — integer
- `passengers` — array
  each record in `passengers` has:
  - `first_name` — string
  - `last_name` — string
  - `dob` — string
- `payment_history` — array
  each record in `payment_history` has:
  - `payment_id` — string
  - `amount` — integer
- `created_at` — string
- `total_baggages` — integer
- `nonfree_baggages` — integer
- `insurance` — string — one of no, yes

### `users.json` — object of 500 records keyed by identifier
Holds user profile details (identity, contact/address, membership, saved passengers, payment methods, and reservation references) so the service can personalize booking and present a user’s stored information.
Keys look like: mia_li_3668, mei_hernandez_8984, aarav_nguyen_1055

- `name` — object
  each record in `name` has:
  - `first_name` — string
  - `last_name` — string
- `address` — object
  each record in `address` has:
  - `address1` — string
  - `address2` — string
  - `city` — string
  - `country` — string
  - `state` — string
  - `zip` — string
- `email` — string
- `dob` — string
- `payment_methods` — object
  each record in `payment_methods` has:
  - `source` — string — one of certificate, credit_card, gift_card
  - `brand` — string — one of mastercard, visa
  - `last_four` — string
  - `id` — string
  - `amount` — integer
- `saved_passengers` — array
  each record in `saved_passengers` has:
  - `first_name` — string
  - `last_name` — string
  - `dob` — string
- `membership` — string — one of gold, regular, silver
- `reservations` — array
