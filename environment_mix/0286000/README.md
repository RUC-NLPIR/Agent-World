# AeroLedger Reservations Hub

AeroLedger Reservations Hub is a flight reservation service that maintains user profiles, flight schedule/inventory data, and reservation records.

## Datastore

### `flights.json` — object of 300 records keyed by identifier
Holds flight routes and per-date operational details (including timing, seat availability, and prices) so the service can present and track flight options over time.
Keys look like: HAT001, HAT002, HAT003

- `origin` — string
- `destination` — string
- `flight_number` — string
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

### `users.json` — object of 500 records keyed by identifier
Holds user profile, contact, saved passenger, and payment-method information so the service can associate reservations and booking inputs with a user.
Keys look like: mia_li_3668, mei_hernandez_8984, aarav_nguyen_1055

- `user_id` — string
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
  - `id` — string
  - `brand` — string — one of mastercard, visa
  - `last_four` — string
  - `amount` — number
- `saved_passengers` — array
  each record in `saved_passengers` has:
  - `first_name` — string
  - `last_name` — string
  - `dob` — string
- `membership` — string — one of gold, regular, silver
- `reservations` — array

### `reservations.json` — object of 2000 records keyed by identifier
Holds booked trip details (itinerary, passengers, payment history, and baggage/insurance selections) so the service can record and retrieve reservations by reservation_id and user_id.
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
