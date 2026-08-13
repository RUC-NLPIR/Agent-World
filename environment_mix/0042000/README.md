# AtlasForge Research Catalog

AtlasForge Research Catalog is a catalog service for browsing and retrieving metadata about machine-learning datasets, models, and research papers.

## Datastore

### `datasets.json` — list of 10 records
Holds dataset metadata (identity, description, tasks/modalities/languages, size, license, and link) so the service can list and filter datasets and return dataset detail pages.

- `id` — string
- `name` — string
- `description` — string
- `tasks` — array
- `modalities` — array
- `languages` — array
- `size` — string
- `license` — string
- `link` — string

### `models.json` — list of 10 records
Holds model metadata (identity, description, primary task, license, and link) so the service can list and filter models and return model detail pages.

- `id` — string
- `name` — string
- `description` — string
- `task` — string
- `license` — string
- `link` — string

### `papers.json` — list of 10 records
Holds research paper summaries and categories so the service can list papers and support category filtering and free-text search over titles and summaries.

- `title` — string
- `summary` — string
- `category` — string
