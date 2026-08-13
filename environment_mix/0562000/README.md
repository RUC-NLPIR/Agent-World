# LatticeFile ShareHub

LatticeFile ShareHub is a file listing and sharing service that tracks file metadata and share grants between users.

## Datastore

### `files.json` — list of 120 records
Holds per-file metadata (identity, name, size, owner, folder, and modification timestamp) so the service can list, retrieve, and search files.

- `file_id` — string
- `name` — string
- `size_kb` — integer
- `owner` — string
- `folder` — string
- `modified` — string

### `shares.json` — list of 80 records
Holds per-file share grants (who a file is shared with and at what permission) so the service can enumerate and create sharing entries.

- `share_id` — string
- `file_id` — string
- `shared_with` — string
- `permission` — string — one of comment, edit, view
