# Workspace File Desk

Workspace File Desk is a simple in-memory file system service for navigating a workspace and performing basic file and directory operations.

## Datastore

### `state.json` — single document
Stores the current working directory and the full node map representing directories and files (including their children lists and file contents) so the service can track and manipulate the workspace state across operations.

- `cwd` — string
- `root_name` — string
- `nodes` — object
  each record in `nodes` has:
  - `type` — string — one of directory, file
  - `children` — array
  - `content` — string
- `random_seed` — integer
