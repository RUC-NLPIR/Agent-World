# Snapshot Repo Inspector

Snapshot Repo Inspector is a small read-only service for inspecting a GitHub repository’s metadata and recent activity from locally stored snapshots.

## Datastore

### `commits.json` — list of 4 records
Holds commit records so the service can list and filter recent repository changes by author, time window, or SHA.

- `sha` — string
- `author` — string — one of Daniel Johnson, Tim Hunter
- `date` — string
- `message` — string

### `contents.json` — list of 19 records
Holds records for entries in the repository root so the service can browse and filter the top-level file/directory listing and related download information.

- `name` — string
- `type` — string — one of dir, file
- `path` — string
- `size` — integer
- `download_url` — string

### `issues_prs.json` — list of 4 records
Holds issue and pull request records so the service can list and filter recent discussion and contribution items, including their pull request links when present.

- `url` — string
- `number` — integer
- `title` — string
- `user` — string — one of JitenRaj, Private0xCC, penne-not-pasta, samuelfavreaubdeb
- `state` — string
- `created_at` — string
- `body` — string
- `pull_request` — object
  each record in `pull_request` has:
  - `url` — string
  - `html_url` — string

### `repo_metadata.json` — single document
Holds a single document describing the repository so the service can present core repo identity, ownership, URLs, and high-level counters in one place.

- `id` — integer
- `node_id` — string
- `name` — string
- `full_name` — string
- `private` — boolean
- `owner` — object
  each record in `owner` has:
  - `login` — string
  - `id` — integer
  - `type` — string
- `html_url` — string
- `description` — string
- `fork` — boolean
- `url` — string
- `created_at` — string
- `updated_at` — string
- `pushed_at` — string
- `git_url` — string
- `ssh_url` — string
- `clone_url` — string
- `svn_url` — string
- `size` — integer
- `stargazers_count` — integer
- `watchers_count` — integer
- `language` — null — nullable
- `has_issues` — boolean
- `has_projects` — boolean
- `has_downloads` — boolean
- `has_wiki` — boolean
- `has_pages` — boolean
- `has_discussions` — boolean
- `forks_count` — integer
- `open_issues_count` — integer
- `default_branch` — string
