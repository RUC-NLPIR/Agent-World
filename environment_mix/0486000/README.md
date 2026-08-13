# Nimbus NoteVault

Nimbus NoteVault is a notes service for listing, retrieving, and sharing notes from an indexed store.

## Datastore

### `notes_index.json` — list of 120 records
Holds the note index (metadata plus full body) so the service can filter notes by date and tag, retrieve a note by id, and share note contents.

- `note_id` — string
- `title` — string
- `date` — string
- `tags` — array
- `body` — string
