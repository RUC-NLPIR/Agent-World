# TraceForge Records Hub

TraceForge Records Hub is a service for browsing project, artifact, and trace records alongside basic repository history and structure metadata.

## Datastore

### `artifacts.json` — list of 50 records
Holds artifact records (including per-project identity, versioning, size, creation time, and metadata) so the service can catalog and describe stored artifacts by project.

- `artifact_id` — string
- `project_name` — string — one of data-preprocessing, gan-experiments, image-classification, nlp-sentiment, reinforcement-learning
- `name` — string
- `version` — string — one of v1, v2, v3, v4, v5
- `digest` — string
- `size_bytes` — integer
- `created_at` — string
- `metadata` — object
  each record in `metadata` has:
  - `framework` — string — one of jax, tensorflow, torch
  - `model_type` — string — one of bert, dqn, gpt, resnet, vae
  - `description` — string

### `branches.json` — list of 6 records
Holds branch records so the service can expose repository branch pointers, the current branch marker, and associated commit/message information.

- `name` — string
- `current` — boolean
- `commit` — string
- `message` — string

### `commits.json` — list of 7 records
Holds commit records so the service can provide repository history entries with author, timestamp, and message details.

- `hash` — string
- `author` — string
- `email` — string
- `date` — string
- `message` — string

### `projects.json` — list of 5 records
Holds project records so the service can list and describe the set of projects it organizes data under, including visibility and tagging metadata.

- `name` — string — one of data-preprocessing, gan-experiments, image-classification, nlp-sentiment, reinforcement-learning
- `entity` — string
- `description` — string
- `visibility` — string — one of private, public
- `created_at` — string
- `updated_at` — string
- `tags` — array

### `repo_structure.json` — single document
Holds a repository file tree snapshot so the service can present the root and file metadata for browsing and lookup.

- `root` — string
- `files` — array
  each record in `files` has:
  - `path` — string
  - `type` — string — one of markdown, python, text
  - `description` — string

### `tags.json` — list of 1 records
Holds tag records so the service can expose repository tag references and their associated commit and message/date metadata.

- `tag` — string
- `commit` — string
- `message` — string
- `date` — string

### `traces.json` — list of 227 records
Holds trace records (including timing, cost, and attributes) so the service can record and report operation-level execution outcomes and performance per project.
Lifecycle field `status`, states observed: error, success

- `id` — string
- `trace_id` — string
- `parent_id` — string — nullable
- `project_name` — string — one of data-preprocessing, gan-experiments, image-classification, nlp-sentiment, reinforcement-learning
- `op_name` — string
- `display_name` — string
- `started_at` — string
- `ended_at` — string
- `status` — string — one of error, success
- `latency_ms` — integer
- `costs` — object
  each record in `costs` has:
  - `prompt_tokens_total_cost` — number
  - `completion_tokens_total_cost` — number
  - `total_cost` — number
- `attributes` — object
  each record in `attributes` has:
  - `model_name` — string
  - `token_count` — integer

### `users.json` — list of 10 records
Holds user records so the service can identify and list users associated with an entity and their basic profile/contact metadata.

- `user_id` — string
- `username` — string
- `email` — string
- `entity` — string
- `created_at` — string
