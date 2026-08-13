# GalleryVault Collection Navigator

GalleryVault Collection Navigator is a service for browsing and retrieving Metropolitan Museum of Art collection departments and object records via search and object lookup tools.

## Datastore

### `met.json` — single document
Holds a local snapshot of Met departments and keyed museum object details so the service can serve department listings and object search/lookup results from stored data.

- `departments` — array
  each record in `departments` has:
  - `departmentId` — integer
  - `displayName` — string
- `objects` — object
  each record in `objects` has:
  - `objectID` — integer
  - `title` — string
  - `artistDisplayName` — string
  - `objectDate` — string
  - `department` — string
  - `departmentId` — integer
  - `medium` — string
  - `isHighlight` — boolean
  - `primaryImage` — string
