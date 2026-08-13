# Keystone Trading Session Hub

Keystone Trading Session Hub is a trading service that tracks a user's brokerage-like session state for stock information, orders, account data, and watchlist activity.

## Datastore

### `state.json` — single document
Holds the service's current in-session state (orders, account_info, authentication flag, market and stock snapshots, watch_list, and transaction_history) so the trading tools can read and update a single persisted view of the user's activity.

- `orders` — object
  each record in `orders` has:
  - `id` — integer
  - `order_type` — string — one of Buy, Sell
  - `symbol` — string
  - `price` — number
  - `amount` — integer
  - `status` — string — one of Cancelled, Completed, Open, Pending
- `account_info` — object
  each record in `account_info` has:
  - `account_id` — integer
  - `balance` — number
  - `binding_card` — integer
- `authenticated` — boolean
- `market_status` — string
- `order_counter` — integer
- `stocks` — object
  each record in `stocks` has:
  - `price` — number
  - `percent_change` — number
  - `volume` — number
  - `MA(5)` — number
  - `MA(20)` — number
- `watch_list` — array
- `transaction_history` — array
  each record in `transaction_history` has:
  - `type` — string — one of deposit, withdrawal
  - `amount` — number
  - `timestamp` — string
- `random_seed` — integer
