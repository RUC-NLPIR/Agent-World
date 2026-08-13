# Harborlight Content Hub

Harborlight Content Hub is a simple content service that publishes a small set of authored posts for display on a website.

## Datastore

### `posts.json` — list of 30 records
Holds individual blog-style posts (title, author, body) so the service can render or serve site content.

- `id` — integer
- `title` — string
- `author` — string — one of alice, bob, carol, david, eve
- `body` — string
