# Atlas Catalog Finder

Atlas Catalog Finder is a service for browsing a product catalog and looking up products by id or category.

## Datastore

### `products.json` — list of 20 records
Holds the product catalog entries so the service can return product details and lists for browsing and lookup.

- `product_id` — string
- `name` — string
- `category` — string — one of accessories, audio, displays, furniture, peripherals, storage
- `price` — number
- `stock` — integer
