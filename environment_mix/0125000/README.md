# Zerodha Integration — local MCP environment

This backend stores Zerodha (Kite) authentication sessions and the user’s trading and mutual-fund activity mirrored from Zerodha for API access. Core workflows are: initiate login → capture request_token → exchange for access_token (authenticated session), then fetch portfolio/positions/margins/quotes/historical candles and place/cancel orders and MF SIPs with locally persisted request/response state and lifecycle status.

Repository: https://github.com/aptro/zerodha-mcp
Homepage: https://smithery.ai/server/@aptro/zerodha-mcp

## Datastore

- `users.json` — End-users of the integration (one per Zerodha client_id), used to scope auth sessions and persisted order history. (12 rows; fields: ['id', 'zerodha_client_id', 'email', 'phone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(zerodha_client_id)
  - constraint: status in ('active','suspended','deleted')
- `auth_sessions.json` — Tracks login initiation, request_token capture, and authenticated Kite access_token sessions. Powers initiate_login, get_request_token, check_and_authenticate. (18 rows; fields: ['id', 'user_id', 'state', 'login_url', 'redirected_at', 'request_token', 'request_token_expires_at', 'access_token', 'access_token_expires_at', 'kite_user_id', 'status', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'login_initiated', 'request_token_received', 'authenticated', 'expired', 'revoked', 'failed']
  - constraint: fk(user_id) references users(id)
  - constraint: unique(state)
  - constraint: request_token is null or length(request_token) >= 5
  - constraint: access_token is null or length(access_token) >= 10
- `portfolio_snapshots.json` — Materialized snapshots of holdings, positions and margins returned from Zerodha for fast reads and audit. Powers get_holdings, get_positions, get_margins. (18 rows; fields: ['id', 'user_id', 'auth_session_id', 'snapshot_type', 'as_of', 'status', 'payload', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'failed']
  - constraint: fk(user_id) references users(id)
  - constraint: auth_session_id is null or fk(auth_session_id) references auth_sessions(id)
  - constraint: snapshot_type in ('holdings','positions','margins')
  - constraint: source = 'kite_api'
- `market_data_requests.json` — Stores quote and historical-data fetch requests/responses for caching, debugging, and rate-limit protection. Powers get_quote and get_historical_data. (19 rows; fields: ['id', 'user_id', 'auth_session_id', 'request_type', 'symbols', 'instrument_token', 'from_date', 'to_date', 'interval', 'status', 'response_payload', 'http_status', 'error_message', 'requested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'succeeded', 'failed']
  - constraint: fk(user_id) references users(id)
  - constraint: auth_session_id is null or fk(auth_session_id) references auth_sessions(id)
  - constraint: request_type in ('quote','historical')
  - constraint: request_type = 'quote' implies symbols is not null
- `orders.json` — Unified storage for equity/derivative orders and mutual fund orders/SIPs, including local request parameters and upstream IDs. Powers place_order, get_mf_orders, place_mf_order, cancel_mf_order, get_mf_sips, place_mf_sip, modify_mf_sip, cancel_mf_sip. (19 rows; fields: ['id', 'user_id', 'auth_session_id', 'order_domain', 'upstream_order_id', 'upstream_sip_id', 'tradingsymbol', 'exchange', 'transaction_type', 'quantity', 'product', 'order_type', 'price', 'trigger_price', 'amount', 'frequency', 'instalments', 'initial_amount', 'instalment_day', 'tag', 'status', 'upstream_status', 'last_error_message', 'request_payload', 'response_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'submitted', 'accepted', 'rejected', 'cancelled', 'completed', 'active', 'paused', 'failed']
  - constraint: fk(user_id) references users(id)
  - constraint: auth_session_id is null or fk(auth_session_id) references auth_sessions(id)
  - constraint: order_domain in ('kite_order','mf_order','mf_sip')
  - constraint: order_domain = 'kite_order' implies (tradingsymbol is not null and exchange is not null and transaction_type is not null and quantity is not null and product is not null and order_type is not null)
- `mf_instruments.json` — Cached mutual fund instrument master list from Zerodha. Powers get_mf_instruments and supports validation for MF orders/SIPs. (18 rows; fields: ['id', 'tradingsymbol', 'amc', 'name', 'scheme_type', 'is_purchase_allowed', 'is_redemption_allowed', 'status', 'raw_payload', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(tradingsymbol)
  - constraint: status in ('active','inactive')
  - constraint: last_refreshed_at >= created_at

## Business rules enforced by the tools

- All tools that call Zerodha upstream (holdings/positions/margins/quote/historical/place_order/MF actions) must require an auth_sessions row with status='authenticated' for the user and access_token_expires_at > now(); otherwise check_and_authenticate should create/login_initiated a new session and report not authenticated.
- initiate_login must create a new auth_sessions row with status='login_initiated', a unique state, and a login_url; any previous authenticated session for the same user may be left as-is but is considered stale if expired.
- get_request_token must return the request_token from the most recent auth_sessions row for the user where status in ('login_initiated','request_token_received') ordered by created_at desc; if none exists, it must return a not-found error.
- When a request_token is captured, the corresponding auth_sessions row must transition to status='request_token_received' and set request_token_expires_at within a short TTL (e.g., <= 15 minutes) from redirected_at.
- Portfolio reads (get_holdings/get_positions/get_margins) must write a portfolio_snapshots row per call; status='fresh' on success and 'failed' with error detail on failure.
- get_quote must persist a market_data_requests row with request_type='quote' and symbols populated; get_historical_data must persist request_type='historical' with instrument_token/from_date/to_date/interval populated.
- place_order must create an orders row with order_domain='kite_order', status='submitted', and must enforce: quantity>=1; order_type=LIMIT => price required; order_type in (SL,SL-M) => trigger_price required.
- place_mf_order must create an orders row with order_domain='mf_order', amount>0, transaction_type in (BUY,SELL), and set upstream_order_id on success; cancel_mf_order must only be allowed when order_domain='mf_order' and status in ('submitted','accepted') and then transition to 'cancelled' if upstream cancel succeeds.
- place_mf_sip must create an orders row with order_domain='mf_sip', amount>0, instalments>=6, frequency in (weekly,monthly,quarterly); modify_mf_sip must only operate on order_domain='mf_sip' with upstream_sip_id not null and status in ('active','paused') and may transition between 'active' and 'paused'; cancel_mf_sip must transition to 'cancelled' when upstream confirms.
- get_mf_orders/get_mf_sips should be served from orders where order_domain='mf_order' or 'mf_sip' respectively, optionally backfilled by upstream and upserted by unique(upstream_order_id/upstream_sip_id).
- get_mf_instruments must read from mf_instruments; refresh jobs must upsert by unique(tradingsymbol) and mark instruments not seen in the latest refresh as status='inactive'.