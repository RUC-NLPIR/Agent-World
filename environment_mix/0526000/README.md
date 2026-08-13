# StrataConfig Studio

StrataConfig Studio is a small configuration-and-experiment-tracking service that keeps file-system access settings, feature rollout switches, hyperparameter tuning data, and model training results.

## Datastore

### `fs_manifest.json` — single document
Holds the workspace root and the list of allowed directories so the service can scope where file operations are permitted.

- `allowed_directories` — array
- `root` — string

### `feature_flags.json` — object of 4 records keyed by identifier
Holds per-flag rollout settings so the service can track which product features are enabled, at what rollout percentage, and who owns them.
Keys look like: multi_currency, new_checkout, realtime_dashboards

- `enabled` — boolean
- `rollout_pct` — integer
- `owner` — string — one of alice, bob, carol, david

### `hparams.json` — object of 2 records keyed by identifier
Holds hyperparameter search space definitions and the currently recorded best trial so the service can track tuning inputs and outcomes.
Keys look like: search_space, best_trial

- `lr` — array
- `batch_size` — array
- `aug` — array
- `run` — integer
- `acc` — number
- `params` — object
  each record in `params` has:
  - `lr` — number
  - `batch_size` — integer
  - `aug` — string

### `results.json` — list of 5 records
Holds per-run training metrics and settings so the service can record and review experiment outcomes over multiple runs.

- `run` — integer
- `model` — string — one of resnet18, resnet50
- `lr` — number
- `epochs` — integer
- `acc` — number
- `loss` — number
- `aug` — string — one of cutmix, mixup
