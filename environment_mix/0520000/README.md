# Helios Paper Vault

Helios Paper Vault is a service for searching, downloading, listing, and reading arXiv papers as stored markdown resources.

## Datastore

### `papers.json` — object of 53 records keyed by identifier
Holds stored arXiv paper metadata and full markdown content so the service can list available papers and return readable paper text after download/conversion.
Keys look like: 1706.03762, 1810.04805, 2005.14165

- `id` — string
- `title` — string
- `authors` — array
- `categories` — array
- `published` — string
- `summary` — string
- `markdown` — string
