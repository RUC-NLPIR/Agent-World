# Bible Verse Access Server — local MCP environment

This backend stores Bible translations, their canonical book structures (books/chapters/verses), and the verse text per translation. The main workflows are listing available translations/books/chapters and fetching either a specific passage by reference or a random verse optionally constrained to a subset of books or testament scope (OT/NT).

Repository: https://github.com/HarunGuclu/bible-mcp
Homepage: https://smithery.ai/server/@HarunGuclu/bible-mcp

## Datastore

- `translations.json` — Catalog of Bible translations made available by the service (e.g., WEB). Used by all read endpoints to scope book structure and verse text. (12 rows; fields: ['id', 'code', 'name', 'language', 'provider', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(code)
  - constraint: code = lower(code)
  - constraint: language length(language) between 2 and 10
- `books.json` — Book catalog per translation (or shared canon). Supports listing books and restricting random verse selection to specific books or OT/NT. (30 rows; fields: ['id', 'translation_id', 'book_code', 'name', 'short_name', 'testament', 'ordinal', 'chapter_count', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(translation_id, book_code)
  - constraint: book_code = upper(book_code)
  - constraint: ordinal >= 1
  - constraint: chapter_count >= 1
- `chapters.json` — Chapter index per book and translation. Used to list chapters for a given book and to support efficient random verse selection. (30 rows; fields: ['id', 'translation_id', 'book_id', 'chapter_number', 'verse_count', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(translation_id, book_id, chapter_number)
  - constraint: chapter_number >= 1
  - constraint: verse_count >= 1
  - constraint: fk(translation_id) references translations(id) on delete restrict
- `verses.json` — Atomic verse content per translation/book/chapter/verse. Used by get_bible_verse and as the sampling population for get_random_bible_verse. (32 rows; fields: ['id', 'translation_id', 'book_id', 'chapter_id', 'chapter_number', 'verse_number', 'text', 'paragraph_break_before', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(translation_id, book_id, chapter_number, verse_number)
  - constraint: chapter_number >= 1
  - constraint: verse_number >= 1
  - constraint: length(text) > 0
- `passage_requests.json` — Request log and parsing outcome for reference-based and random verse retrieval. Supports observability, abuse detection, and reproducible results for a given request. (32 rows; fields: ['id', 'request_type', 'translation_code', 'translation_id', 'input_reference', 'input_book_ids', 'resolved_book_codes', 'parsed_start_chapter', 'parsed_start_verse', 'parsed_end_chapter', 'parsed_end_verse', 'result_verse_ids', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'fulfilled', 'not_found', 'invalid_request', 'error']
  - constraint: request_type = 'reference_lookup' implies input_reference is not null
  - constraint: request_type = 'random_verse' implies input_book_ids is null or length(input_book_ids) > 0
  - constraint: translation_code = lower(translation_code)
  - constraint: parsed_start_chapter >= 1 when not null

## Business rules enforced by the tools

- list_bible_translations returns translations where status in ('active','deprecated') ordered by code; disabled translations are not returned.
- list_bible_books(translation) resolves translations.code = translation (default 'web'); if not found or status='disabled', return empty list or not_found without exposing disabled metadata.
- list_bible_chapters(book, translation) resolves the book by (translations.code, books.book_code) and requires books.status='active' and translations.status in ('active','deprecated'); returns chapters with status='active' ordered by chapter_number.
- get_bible_verse(reference, translation) must parse the reference into (book_code, start chapter/verse, optional end chapter/verse). If parsing fails, create a passage_requests row with status='invalid_request'.
- get_bible_verse must only return verses with status='active' and within the specified range; if none exist, mark passage_requests.status='not_found'.
- get_random_bible_verse(book_ids) uses translation 'web' implicitly (since tool has no translation parameter) and samples uniformly from verses.status='active' in that translation, filtered by: if book_ids='OT' or 'NT' then books.testament matches; if book_ids is comma-separated codes then restrict to those books; if book_ids null then all active books.
- For get_random_bible_verse, any unknown book code in a comma-separated list results in status='invalid_request' (do not silently ignore) unless the list is empty/whitespace (treated as null).
- FK integrity: chapters.book_id must reference a books row with the same translation_id; verses.chapter_id and verses.book_id must reference rows with the same translation_id, and verses.chapter_number must equal chapters.chapter_number.
- Uniqueness: within a translation and book, a given (chapter_number, verse_number) maps to exactly one verses row; within a translation, a book_code maps to exactly one books row.
- Status enforcement: entities with status='disabled' must never be returned by list/get tools; only active (and for translations, optionally deprecated) can be served.