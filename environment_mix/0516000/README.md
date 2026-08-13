# HelioSupport Knowledge Hub

HelioSupport Knowledge Hub is a knowledge-base service for organizing, retrieving, searching, and updating help articles using categories and tags.

## Datastore

### `categories.json` — list of 8 records
Holds the set of knowledge-base categories and their descriptions so the service can group articles into browseable sections.

- `category_id` — string — one of cat-1, cat-2, cat-3, cat-4, cat-5, cat-6, cat-7, cat-8
- `name` — string — one of API Reference, Account Management, Best Practices, Billing, Getting Started, Integrations, Security, Troubleshooting
- `description` — string

### `tags.json` — list of 20 records
Holds tag definitions so the service can label and filter articles by shared topics.

- `tag_id` — string
- `name` — string

### `articles.json` — list of 120 records
Holds knowledge-base articles, including their category assignment, tag list, content, and view counts so the service can present and search documentation content.

- `article_id` — string
- `title` — string
- `category_id` — string — one of cat-1, cat-2, cat-3, cat-4, cat-5, cat-6, cat-7, cat-8
- `tags` — array
- `body` — string
- `views` — integer
