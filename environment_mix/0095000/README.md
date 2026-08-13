# Quran.com API Server — local MCP environment

This backend stores Quran core metadata (chapters, verses), localized content (chapter info, translations, tafsir), and recitation catalog data (reciters, styles, verse-level audio). The main workflows are read-heavy: listing chapters/languages/resources, fetching verses by multiple indices (chapter/page/juz/hizb/rub/verse_key/random) with optional word/translation/tafsir/audio enrichments, and running full-text searches with pagination and language boosting.

Repository: https://github.com/djalal/quran-mcp-server
Homepage: https://smithery.ai/server/@djalal/quran-mcp-server

## Datastore

- `languages.json` — Supported UI/content languages used to localize chapter names/info, translation/tafsir metadata, and reciter names. (25 rows; fields: ['id', 'code', 'name_local', 'name_english', 'rtl', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(code)
  - constraint: length(code) between 2 and 10
  - constraint: code matches ^[a-zA-Z-]+$
  - constraint: rtl in (true,false)
- `chapters.json` — Surah (chapter) canonical metadata plus localized names and chapter info bodies. (30 rows; fields: ['id', 'chapter_number', 'revelation_place', 'verses_count', 'bismillah_pre', 'name_arabic', 'localized', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'hidden']
  - constraint: unique(chapter_number)
  - constraint: chapter_number between 1 and 114
  - constraint: verses_count > 0
  - constraint: revelation_place in ('makkah','madinah')
- `verses.json` — Ayah canonical text and indexing fields to support retrieval by chapter, page, juz, hizb, rub el hizb, verse_key, and random selection. Also stores word-level data as JSON and supports per-verse enrichments. (39 rows; fields: ['id', 'chapter_id', 'chapter_number', 'verse_number', 'verse_key', 'text_uthmani', 'page_number', 'juz_number', 'hizb_number', 'rub_el_hizb_number', 'words_json', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'hidden']
  - constraint: foreign key (chapter_id) references chapters.id
  - constraint: unique(verse_key)
  - constraint: unique(chapter_id, verse_number)
  - constraint: chapter_number between 1 and 114
- `resources.json` — Catalog of available translations, tafsirs, reciters and recitation styles. Also stores verse-level content/audio mappings for each resource. Serves tools: translations, translation-info, tafsirs, tafsir-info, tafsir, chapter-reciters, recitation-styles, and verse enrichment via `translations`, `tafsirs`, and `audio` parameters. (37 rows; fields: ['id', 'resource_type', 'vendor_numeric_id', 'language_code', 'name', 'author_name', 'description', 'slug', 'metadata_json', 'content_items', 'localizations', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: resource_type in ('translation','tafsir','reciter','recitation_style')
  - constraint: unique(resource_type, vendor_numeric_id) where vendor_numeric_id is not null
  - constraint: foreign key (language_code) references languages.code
  - constraint: for resource_type in ('translation','tafsir'): vendor_numeric_id is not null
- `search_queries.json` — Persisted search requests and cached result sets for the `search` tool, including pagination, language boosting, and performance metrics. Supports analytics, rate limiting, and caching of top queries. (39 rows; fields: ['id', 'query_text', 'language_code', 'page', 'size', 'result_verse_ids', 'result_total', 'engine_metadata_json', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['completed', 'failed']
  - constraint: length(query_text) > 0
  - constraint: page >= 1
  - constraint: size between 1 and 50
  - constraint: foreign key (language_code) references languages.code

## Business rules enforced by the tools

- `list-chapters(language)` returns chapters where chapters.status='published' and uses chapters.localized entry matching language; if missing, fall back to a default language (e.g., 'en') without failing the request.
- `GET-chapter(language,id)` accepts id as integer/string digits and maps to chapters.chapter_number; reject ids outside 1-114.
- `info(language,chapter_id)` maps chapter_id to chapters.chapter_number; returns the chapter_info_html from chapters.localized for the requested language (with fallback).
- All verse listing tools (`verses-by_*`) only return verses where verses.status='published'. Pagination uses `page` and `per_page` with defaults and clamps per_page to a safe maximum (<= 50).
- When `words` is truthy in a verses endpoint, include verses.words_json; `word_fields` restricts keys projected from each word object; unknown requested fields are ignored (or validated and rejected consistently).
- When `translations` is provided, parse comma-separated numeric ids; each must match an active resources row with resource_type='translation' and vendor_numeric_id in the list; attach translation content_items for returned verses; `translation_fields` controls projection (e.g., text, resource_name, language_code).
- When `tafsirs` is provided, parse comma-separated numeric ids; each must match an active resources row with resource_type='tafsir' and vendor_numeric_id; attach tafsir content_items for returned verses; `fields` on tafsir tool controls which tafsir attributes are returned.
- When `audio` is provided, treat it as reciter vendor_numeric_id; it must match an active resources row with resource_type='reciter'; attach audio content_items for returned verses.
- `random_verse` selects uniformly from verses where status='published' (optionally constrained by availability of requested enrichments if the implementation chooses consistency), then applies the same enrichment rules (words/translations/tafsirs/audio).
- `juzs` returns the static set of 30 juz numbers with their boundary verse_keys derived from verses ordering (min/max verse_key per juz_number).
- `translations(language)` filters resources by resource_type='translation' and status='active'; if language is provided, returns those whose language_code matches OR have a localization for that language.
- `translation-info(translation_id)` resolves translation_id to resources.vendor_numeric_id where resource_type='translation' and returns metadata_json/author_name/description; reject if not found or disabled.
- `tafsirs(language)` and `tafsir-info(tafsir_id)` mirror the translation rules for resource_type='tafsir'.
- `tafsir(tafsir_id, chapter_number|juz_number|page_number|hizb_number|rub_el_hizb_number|verse_key)` must have exactly one scope filter (at most one of those fields present); it resolves the target verses via verses indices and returns the tafsir content_items for those verses (or a single verse for verse_key).
- `chapter-reciters(language)` returns resources where resource_type='reciter' and status='active', using localized names if available for the requested language (fallback to resources.name).
- `recitation-styles` returns resources where resource_type='recitation_style' and status='active'.
- `languages(language)` returns all active languages; if a `language` param is provided, it is treated as a display-language preference (may affect sorting/display names) but does not filter out other languages.