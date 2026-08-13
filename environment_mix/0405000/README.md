# Pokemon TCG Card Search — local MCP environment

This backend supports a Pokemon TCG card search service and a card market-price lookup feature. It stores a normalized catalog of cards and their printings plus periodic price snapshots from external marketplaces, and records each API lookup for auditing and rate-limiting.

Repository: https://github.com/jlgrimes/ptcg-mcp
Homepage: https://smithery.ai/server/@jlgrimes/ptcg-mcp

## Datastore

- `api_clients.json` — Represents an authenticated client (or anonymous install) using the MCP server. Used for request attribution, quotas, and auditability even though tools expose no explicit parameters. (12 rows; fields: ['id', 'display_name', 'api_key_hash', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(api_key_hash) where api_key_hash is not null
  - constraint: requests_per_minute_limit between 1 and 600
  - constraint: requests_per_day_limit between 1 and 200000
- `cards.json` — Canonical Pokemon TCG card entries, one per unique printing (set + collector number + variant). Serves search results and price lookups. (18 rows; fields: ['id', 'external_id', 'name', 'supertype', 'subtypes', 'set_code', 'set_name', 'collector_number', 'rarity', 'artist', 'images', 'tcgplayer_product_id', 'cardmarket_product_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'blocked']
  - constraint: unique(set_code, collector_number, name)
  - constraint: unique(external_id) where external_id is not null
  - constraint: unique(tcgplayer_product_id) where tcgplayer_product_id is not null
  - constraint: unique(cardmarket_product_id) where cardmarket_product_id is not null
- `price_snapshots.json` — Time-series snapshots of market pricing for a given card from a given source. Used by the pokemon-card-price tool to return current market price (latest snapshot). (18 rows; fields: ['id', 'card_id', 'source', 'currency', 'market_price', 'low_price', 'high_price', 'direct_low_price', 'snapshot_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'superseded', 'invalid']
  - constraint: foreign key(card_id) references cards(id) on delete cascade
  - constraint: currency in ('USD','EUR','GBP','JPY','CAD','AUD')
  - constraint: market_price is null or market_price >= 0
  - constraint: low_price is null or low_price >= 0
- `search_queries.json` — Audit log of search requests performed via pokemon-card-search, including normalized query text and server-side filters derived from the client request/context. (19 rows; fields: ['id', 'client_id', 'query_text', 'filters', 'result_count', 'latency_ms', 'status', 'error_code', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'rate_limited']
  - constraint: foreign key(client_id) references api_clients(id) on delete set null
  - constraint: result_count >= 0
  - constraint: latency_ms >= 0
  - constraint: query_text is null or length(query_text) <= 512
- `price_lookups.json` — Audit log of price lookup requests performed via pokemon-card-price, including the resolved card and the snapshot used to answer 'current' price. (19 rows; fields: ['id', 'client_id', 'card_id', 'price_snapshot_id', 'lookup_key', 'source_preference', 'status', 'latency_ms', 'error_code', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'not_found', 'failed', 'rate_limited']
  - constraint: foreign key(client_id) references api_clients(id) on delete set null
  - constraint: foreign key(card_id) references cards(id) on delete set null
  - constraint: foreign key(price_snapshot_id) references price_snapshots(id) on delete set null
  - constraint: latency_ms >= 0

## Business rules enforced by the tools

- pokemon-card-search must create a search_queries row for every request, setting status to succeeded/failed/rate_limited and recording latency_ms and result_count (0 on failure).
- pokemon-card-price must create a price_lookups row for every request, setting card_id if a card can be resolved and price_snapshot_id if a current snapshot exists.
- A price_snapshot is considered 'current' only if it is the latest snapshot_at for (card_id, source) and status=current; inserting a new snapshot for the same (card_id, source) must mark the previous current snapshot as superseded in the same transaction.
- Requests attributed to an api_client must be rate-limited such that counts in a sliding 60-second window do not exceed requests_per_minute_limit and counts per UTC day do not exceed requests_per_day_limit; if exceeded, the tool must return an error and log status=rate_limited.
- cards with status=blocked must not be returned in search results and must not be eligible for price lookup responses (lookup should return not_found while still logging the attempt).
- FK integrity must be enforced: price_snapshots.card_id must reference an existing card; deleting a card must cascade delete its price_snapshots but preserve audit logs (search_queries/price_lookups) by setting nullable FKs to null.
- If a lookup returns succeeded, then price_snapshot_id must be non-null and reference a snapshot whose card_id equals price_lookups.card_id and status=current at the time of response.