# Chronicle Repository Navigator

Chronicle Repository Navigator is a service for browsing a repository’s history and structure, including commits, branches, tags, and the file tree.

## Datastore

### `branches.json` — list of 6 records
Holds branch pointers with their current/active indicator and tip commit metadata so the service can present and filter the repository’s branch list.

- `name` — string
- `current` — boolean
- `commit` — string
- `message` — string

### `commits.json` — list of 7 records
Holds commit metadata (identity, author info, timestamp, and message) so the service can list and retrieve items from the repository history.

- `hash` — string
- `author` — string
- `email` — string
- `date` — string
- `message` — string

### `repo_structure.json` — single document
Holds a snapshot of the repository root and its files with basic metadata so the service can expose and search the file tree.

- `root` — string
- `files` — array
  each record in `files` has:
  - `path` — string
  - `type` — string — one of markdown, python, text
  - `description` — string

### `tags.json` — list of 1 records
Holds tag references to commits along with annotation metadata so the service can list and retrieve repository tags.

- `tag` — string
- `commit` — string
- `message` — string
- `date` — string
