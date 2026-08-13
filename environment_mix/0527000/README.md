# Aegis CommandOps Registry

Aegis CommandOps Registry is a service for describing and governing an allowed terminal command/tool environment while tracking ML-style projects and their related assets and execution traces.

## Datastore

### `artifacts.json` — list of 50 records
Holds versioned project artifacts with digests, sizes, timestamps, and metadata so the service can catalog and describe produced assets by project.

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

### `commands.json` — list of 59 records
Holds the available terminal command definitions (name, description, category) so the service can present a curated command catalog.

- `name` — string
- `description` — string
- `category` — string

### `projects.json` — list of 5 records
Holds project descriptors (identity, visibility, timestamps, tags) so the service can organize runs, artifacts, and traces under named projects.

- `name` — string — one of data-preprocessing, gan-experiments, image-classification, nlp-sentiment, reinforcement-learning
- `entity` — string
- `description` — string
- `visibility` — string — one of private, public
- `created_at` — string
- `updated_at` — string
- `tags` — array

### `security_rules.json` — single document
Holds the terminal security configuration (allowed/disallowed commands, tools, and shell operator setting) so the service can communicate its execution policy.

- `allow_shell_operators` — boolean
- `allowed_commands` — array
- `disallowed_commands` — array
- `allowed_tools` — array

### `toolsets.json` — single document
Holds the terminal toolset definition (tools, allowed shell operators, default directory) so the service can describe the tool bundle exposed to consumers.

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

### `traces.json` — list of 227 records
Holds per-operation trace records with timing, status, costs, and attributes so the service can record and analyze execution activity.
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
Holds user profiles so the service can associate activity and ownership with identifiable users.

- `user_id` — string
- `username` — string
- `email` — string
- `entity` — string
- `created_at` — string
