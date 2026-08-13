# Beacon Subscription Ledger

Beacon Subscription Ledger is a small customer-and-subscription reporting service that exposes customer lookup/listing and MRR aggregation tools.

## Datastore

### `customers.json` — list of 20 records
Holds customer identities, contact information, tier, and current MRR so the service can list customers, retrieve a specific customer, and compute aggregate and per-tier MRR.

- `customer_id` — string
- `name` — string
- `email` — string
- `tier` — string — one of enterprise, pro, starter
- `mrr` — integer
