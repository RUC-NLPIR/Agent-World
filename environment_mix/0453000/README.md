# Hearthstone Bibliographic Gateway

Hearthstone Bibliographic Gateway is a service that looks up book and author information from Open Library and keeps retrieved metadata in a local store.

## Datastore

### `openlibrary.json` — object of 4 records keyed by identifier
Stores cached Open Library lookup results keyed by identifier so the service can reuse previously retrieved book metadata across requests.
Keys look like: books_by_title, authors_by_name, author_info

- `the hobbit` — object
  each record in `the hobbit` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the fellowship of the ring` — object
  each record in `the fellowship of the ring` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the two towers` — object
  each record in `the two towers` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the return of the king` — object
  each record in `the return of the king` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the silmarillion` — object
  each record in `the silmarillion` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `1984` — object
  each record in `1984` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `animal farm` — object
  each record in `animal farm` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `homage to catalonia` — object
  each record in `homage to catalonia` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `pride and prejudice` — object
  each record in `pride and prejudice` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `emma` — object
  each record in `emma` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `sense and sensibility` — object
  each record in `sense and sensibility` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `great expectations` — object
  each record in `great expectations` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `a tale of two cities` — object
  each record in `a tale of two cities` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `oliver twist` — object
  each record in `oliver twist` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `a christmas carol` — object
  each record in `a christmas carol` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the old man and the sea` — object
  each record in `the old man and the sea` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `a farewell to arms` — object
  each record in `a farewell to arms` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `for whom the bell tolls` — object
  each record in `for whom the bell tolls` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the great gatsby` — object
  each record in `the great gatsby` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `tender is the night` — object
  each record in `tender is the night` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `moby-dick` — object
  each record in `moby-dick` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `bartleby the scrivener` — object
  each record in `bartleby the scrivener` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `war and peace` — object
  each record in `war and peace` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `anna karenina` — object
  each record in `anna karenina` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `crime and punishment` — object
  each record in `crime and punishment` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the brothers karamazov` — object
  each record in `the brothers karamazov` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `notes from underground` — object
  each record in `notes from underground` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the adventures of huckleberry finn` — object
  each record in `the adventures of huckleberry finn` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the adventures of tom sawyer` — object
  each record in `the adventures of tom sawyer` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `jane eyre` — object
  each record in `jane eyre` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `foundation` — object
  each record in `foundation` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `i, robot` — object
  each record in `i, robot` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `foundation and empire` — object
  each record in `foundation and empire` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `2001: a space odyssey` — object
  each record in `2001: a space odyssey` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `childhood's end` — object
  each record in `childhood's end` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `rendezvous with rama` — object
  each record in `rendezvous with rama` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `a wizard of earthsea` — object
  each record in `a wizard of earthsea` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the left hand of darkness` — object
  each record in `the left hand of darkness` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `the colour of magic` — object
  each record in `the colour of magic` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
- `mort` — object
  each record in `mort` has:
  - `title` — string
  - `author_name` — array
  - `first_publish_year` — integer
  - `key` — string
  - `isbn` — array
