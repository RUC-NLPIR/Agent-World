# Domino's Pizza API Integration Server — local MCP environment

This backend stores Domino's store discovery results, store menus, and a session-scoped ordering workflow (draft order -> validated/priced -> placed -> tracked). It models orders and order items, supports add/remove mutations, and persists downstream Domino's identifiers and responses needed to validate, price, place, and track orders.

Repository: https://github.com/mdwoicke/mcp-dominos-pizza
Homepage: https://smithery.ai/server/@mdwoicke/mcp-dominos-pizza

## Datastore

- `sessions.json` — Represents an API client session for the integration server. The 'current order' and store context are tracked here because multiple tools act on the order 'from the session'. (20 rows; fields: ['id', 'status', 'client_label', 'current_store_id', 'current_order_id', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: expires_at > created_at
  - constraint: current_order_id IS NULL OR current_order_id references orders.id
  - constraint: current_store_id IS NULL OR current_store_id references stores.id
- `stores.json` — Domino's store directory entries returned from nearby store discovery. Includes minimal store attributes plus raw provider payload for forward compatibility. (29 rows; fields: ['id', 'provider', 'provider_store_number', 'name', 'address_line1', 'address_line2', 'city', 'region', 'postal_code', 'country_code', 'phone', 'latitude', 'longitude', 'is_open', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `provider`: ['dominos']
  - constraint: unique(provider, provider_store_number)
  - constraint: latitude IS NULL OR (latitude >= -90 AND latitude <= 90)
  - constraint: longitude IS NULL OR (longitude >= -180 AND longitude <= 180)
- `store_menus.json` — Cached menu snapshots for a store (and optionally a service method like delivery/carryout). Used to serve getMenu and to validate order items against known product codes/options. (20 rows; fields: ['id', 'store_id', 'service_method', 'currency', 'menu_version', 'status', 'menu_payload', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'superseded']
  - constraint: store_id references stores.id
  - constraint: unique(store_id, service_method, fetched_at)
  - constraint: service_method IN ('delivery','carryout','unknown')
- `orders.json` — A session-scoped Domino's order. Stores delivery/carryout details, pricing/validation results, placement outcome, and provider order identifiers needed for tracking. (24 rows; fields: ['id', 'session_id', 'store_id', 'service_method', 'status', 'customer', 'delivery_address', 'coupon_codes', 'special_instructions', 'validation_result', 'pricing_result', 'total_amount', 'currency', 'payment_method', 'payment_payload', 'provider_order_id', 'provider_tracking_url', 'placed_at', 'last_tracked_at', 'tracking_state', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'validating', 'validated', 'pricing', 'priced', 'placing', 'placed', 'failed', 'cancelled']
  - constraint: session_id references sessions.id
  - constraint: store_id references stores.id
  - constraint: service_method IN ('delivery','carryout')
  - constraint: total_amount IS NULL OR total_amount >= 0
- `order_items.json` — Line items in an order. addItemToOrder/removeItemFromOrder mutate this collection. Stores product codes/options in a provider-compatible shape and keeps per-item pricing returned by priceOrder. (23 rows; fields: ['id', 'order_id', 'status', 'product_code', 'quantity', 'options', 'item_instructions', 'priced_amount', 'currency', 'provider_item_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: order_id references orders.id
  - constraint: quantity >= 1 AND quantity <= 50
  - constraint: priced_amount IS NULL OR priced_amount >= 0
  - constraint: currency IS NULL OR length(currency) = 3

## Business rules enforced by the tools

- findNearbyStores creates/updates stores rows from the provider response (upsert by (provider, provider_store_number)) and MAY set sessions.current_store_id for the caller's active session.
- getMenu requires a store context (either sessions.current_store_id or a store implied by sessions.current_order_id). It fetches from provider and writes a new store_menus row; the previously active menu for (store_id, service_method) becomes stale/superseded.
- createOrder creates an orders row with status='draft' and sets sessions.current_order_id; it must also set orders.store_id and orders.service_method (defaulting from session/store context if available).
- addItemToOrder inserts an order_items row with status='active' for sessions.current_order_id; it is rejected unless the order status is in ('draft','validated','priced').
- removeItemFromOrder never hard-deletes; it transitions order_items.status from 'active' to 'removed' and is rejected if the parent order status is in ('placing','placed','cancelled').
- getOrderState returns the orders row referenced by sessions.current_order_id plus its non-removed order_items.
- validateOrder transitions orders.status to 'validating', calls provider validation, stores orders.validation_result, and transitions to 'validated' on success or 'failed' on error; validation requires at least 1 active order_items row.
- priceOrder transitions orders.status to 'pricing', calls provider pricing, stores orders.pricing_result, orders.total_amount, and per-line order_items.priced_amount, then transitions to 'priced' on success or 'failed' on error.
- placeOrder requires orders.status in ('validated','priced') and required customer/payment fields; it transitions to 'placing', calls provider placement, sets orders.provider_order_id and orders.placed_at, and transitions to 'placed' on success or 'failed' on error.
- trackOrder requires orders.status='placed' and orders.provider_order_id not null; it updates orders.tracking_state and orders.last_tracked_at.
- Only one active (non-expired, non-revoked) session may reference a given current_order_id at a time (enforced by unique(current_order_id) where status='active').
- An order must belong to the same session that is attempting mutations: orders.session_id must equal sessions.id used for the tool call (FK + application check).
- Orders with service_method='delivery' must have delivery_address set before validateOrder/priceOrder/placeOrder; carryout orders must not require delivery_address.