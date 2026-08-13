# PulseShelf Catalog Browser

PulseShelf Catalog Browser is a service for browsing and looking up locally stored lists of trending datasets and models with basic filtering, sorting, and pagination.

## Datastore

### `trending_datasets.json` — list of 16 records
Holds dataset entries and their popularity/metadata fields so the service can list and fetch details for datasets that are currently trending.

- `_id` — string
- `id` — string
- `author` — string
- `disabled` — boolean
- `gated` — boolean/string
- `lastModified` — string
- `likes` — integer
- `trendingScore` — integer
- `private` — boolean
- `sha` — string
- `description` — string
- `downloads` — integer
- `tags` — array
- `createdAt` — string
- `key` — string

### `trending_models.json` — list of 20 records
Holds model entries and their popularity/metadata fields so the service can list and fetch details for models that are currently trending.

- `_id` — string
- `id` — string
- `likes` — integer
- `trendingScore` — integer
- `private` — boolean
- `downloads` — integer
- `tags` — array
- `pipeline_tag` — string — one of image-text-to-text, text-generation
- `library_name` — string
- `createdAt` — string
- `modelId` — string
