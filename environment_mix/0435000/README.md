# Keystone Runtime State & Math Service

Keystone Runtime State & Math Service is a service that persists a small amount of shared runtime state used by the system.

## Datastore

### `state.json` — single document
Holds the service-wide state document so the system can retain a stored random seed across runs.

- `random_seed` — integer
