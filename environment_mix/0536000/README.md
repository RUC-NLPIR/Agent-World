# LedgerSight Commerce Analytics Hub

LedgerSight Commerce Analytics Hub is a service for storing and reporting on commerce data alongside derived analytics and reporting tables.

## Datastore

### `pg_schema.json` — single document
Holds the discovered database schemas and their tables, including captured column metadata and sample row data, so the service can introspect and describe the underlying store for analytics and reporting.

- `schemas` — array
- `tables` — object
  each record in `tables` has:
  - `customers` — object
    each record in `customers` has:
    - `columns` — array
    - `rows` — array
  - `orders` — object
    each record in `orders` has:
    - `columns` — array
    - `rows` — array
  - `products` — object
    each record in `products` has:
    - `columns` — array
    - `rows` — array
  - `order_items` — object
    each record in `order_items` has:
    - `columns` — array
    - `rows` — array
  - `support_tickets` — object
    each record in `support_tickets` has:
    - `columns` — array
    - `rows` — array
  - `daily_revenue` — object
    each record in `daily_revenue` has:
    - `columns` — array
    - `rows` — array
  - `product_views` — object
    each record in `product_views` has:
    - `columns` — array
    - `rows` — array
  - `funnel_events` — object
    each record in `funnel_events` has:
    - `columns` — array
    - `rows` — array
  - `monthly_kpis` — object
    each record in `monthly_kpis` has:
    - `columns` — array
    - `rows` — array
  - `top_products` — object
    each record in `top_products` has:
    - `columns` — array
    - `rows` — array
  - `segment_summary` — object
    each record in `segment_summary` has:
    - `columns` — array
    - `rows` — array
