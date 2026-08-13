# Harborview Repo Navigator

Harborview Repo Navigator is a service that exposes a read-only snapshot of repository and terminal-tooling metadata for downstream browsing and filtering.

## Datastore

### `commands.json` — list of 59 records
Holds command definitions (name, description, category) so the service can document which terminal commands are available and how they are grouped.

- `name` — string
- `description` — string
- `category` — string

### `commits.json` — list of 4 records
Holds commit records (SHA, author, date, message) so the service can summarize recent repository change history.

- `sha` — string
- `author` — string — one of Daniel Johnson, Tim Hunter
- `date` — string
- `message` — string

### `contents.json` — list of 19 records
Holds records for entries in the repository root (files and directories) so the service can list what is available and where it lives.

- `name` — string
- `type` — string — one of dir, file
- `path` — string
- `size` — integer
- `download_url` — string

### `issues_prs.json` — list of 4 records
Holds issue and pull-request records so the service can surface recent discussion and contribution activity.

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
Holds a single document describing the repository’s identity, URLs, feature flags, and high-level counters so the service can present basic repository context.

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

### `security_rules.json` — single document
Holds a single document describing allowed and disallowed commands and permitted tools so the service can publish its terminal security configuration.

- `allow_shell_operators` — boolean
- `allowed_commands` — array
- `disallowed_commands` — array
- `allowed_tools` — array

### `toolsets.json` — single document
Holds a single document describing a terminal toolset (its tools, operator settings, and default directory) so the service can publish the configured execution environment.

- `toolset_name` — string
- `description` — string
- `tools` — array
  each record in `tools` has:
  - `name` — string — one of run_command, show_security_rules
  - `description` — string
  - `parameters` — array
    each record in `parameters` has:
    - `name` — string
    - `type` — string
    - `required` — boolean
    - `description` — string
- `allowed_shell_operators` — boolean
- `default_directory` — string
