# AeroLedger Travel Hub

AeroLedger Travel Hub is a travel-booking backend that authenticates users and supports flight bookings, cancellations, exchange-rate lookups, and credit-card/budget management.

## Datastore

### `state.json` — single document
Holds the service’s working state, including the registered credit cards, flight booking records, authentication token details, and per-user budget configuration, so the service can book/manage travel and track related account context.

- `credit_card_list` — object
  each record in `credit_card_list` has:
  - `card_number` — string — one of 4012888888881881, 4111111111111111, 4222222222222, 5105105105105100, 5500005555555559, 6011111111111117
  - `expiration_date` — string — one of 03/2028, 06/2026, 07/2028, 09/2027, 11/2026, 12/2027
  - `cardholder_name` — string
  - `card_verification_number` — integer
  - `balance` — integer
- `booking_record` — object
  each record in `booking_record` has:
  - `card_id` — string — one of 1432, 3456, 4567, 6789
  - `travel_date` — string
  - `travel_from` — string — one of BOS, CRH, JFK, LAX, OKD, ORD, RMS, SFO
  - `travel_to` — string — one of BOS, JFK, LAX, ORD, RMS, SFO
  - `travel_class` — string — one of business, economy, first
  - `travel_cost` — number
  - `transaction_id` — string
- `access_token` — string
- `token_type` — string
- `token_expires_in` — integer
- `token_scope` — string
- `user_first_name` — string
- `user_last_name` — string
- `budget_limit` — number
- `random_seed` — integer
