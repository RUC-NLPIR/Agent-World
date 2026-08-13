# Lexipedia Insight Service

Lexipedia Insight Service is a service for retrieving, summarizing, and extracting structured information from Wikipedia articles.

## Datastore

### `wikipedia.json` — single document
Stores cached Wikipedia article data—including summaries, section text, links, and key facts—so the service can serve repeated lookups and derived outputs without re-fetching each time.

- `articles` — object
  each record in `articles` has:
  - `title` — string
  - `summary` — string
  - `sections` — object
    each record in `sections` has:
    - `History` — string
    - `Syntax and semantics` — string
    - `Libraries` — string
    - `Early life` — string
    - `Python` — string
    - `Later career` — string
    - `Overview` — string
    - `Approaches` — string
    - `Applications` — string
    - `Subfields` — string
    - `Ethics` — string
    - `Architecture` — string
    - `Training` — string
    - `Types` — string
    - `Impact` — string
    - `Tasks` — string
    - `Methods` — string
    - `Examples` — string
    - `Capabilities` — string
    - `Release` — string
    - `Technology` — string
    - `Products` — string
    - `Governance` — string
    - `Features` — string
    - `Ecosystem` — string
    - `Complexity` — string
    - `Codebreaking` — string
    - `Legacy` — string
    - `Definition` — string
    - `Criticism` — string
    - `Relativity` — string
    - `Nobel Prize` — string
    - `Principia` — string
    - `Voyage` — string
    - `On the Origin of Species` — string
    - `Research` — string
    - `Nobel Prizes` — string
    - `Inventions` — string
    - `Causes` — string
    - `Major events` — string
  - `links` — array
  - `key_facts` — array
