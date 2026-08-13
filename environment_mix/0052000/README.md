# HelioMed Literature Vault

HelioMed Literature Vault is a service for searching PubMed and retaining retrieved article metadata for later lookup and use.

## Datastore

### `pubmed.json` — single document
Holds a keyed set of PubMed article metadata (e.g., title, authors, journal, year, abstract, keywords) so the service can cache and reuse results obtained from PubMed search and fetch operations.

- `articles` — object
  each record in `articles` has:
  - `pmid` — string
  - `title` — string
  - `authors` — array
  - `journal` — string
  - `year` — string — one of 2019, 2020, 2021, 2022, 2023
  - `abstract` — string
  - `keywords` — array
