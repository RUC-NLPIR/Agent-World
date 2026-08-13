# Lattice Recall Graph Service

Lattice Recall Graph Service is a service for storing and querying a lightweight knowledge graph of entities and their relationships with attached freeform observations.

## Datastore

### `memory_graph.json` — single document
Holds the service’s graph snapshot—an array of entities with observation strings and an array of relations between named entities—so the service can persist and operate on a shared knowledge base.

- `entities` — array
  each record in `entities` has:
  - `name` — string
  - `entityType` — string — one of event, location, organization, paper, person, project, technology, university
  - `observations` — array
- `relations` — array
  each record in `relations` has:
  - `from` — string
  - `to` — string
  - `relationType` — string
