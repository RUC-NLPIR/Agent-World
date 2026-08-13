# Office Word Document Server — local MCP environment

This backend stores Word documents managed by an API, including their file locations, metadata, protection state, and a persisted representation of document structure (paragraphs/tables/media) to support read and edit operations. The main workflows are: create/copy documents, append or delete content blocks (paragraphs/headings/tables/pictures/page breaks), apply formatting and styles, manage footnotes/endnotes, run find/replace and search, and export to PDF.

Repository: https://github.com/GongRzhe/Office-Word-MCP-Server
Homepage: https://smithery.ai/server/@GongRzhe/Office-Word-MCP-Server

## Datastore

- `documents.json` — Canonical registry of Word documents known to the server, keyed by file path/filename, including metadata, protection, and derived index fields used for reads/search. (18 rows; fields: ['id', 'directory', 'filename', 'full_path', 'title', 'author', 'status', 'content_version', 'file_sha256', 'file_size_bytes', 'protected_password_hash', 'protection_algorithm', 'last_indexed_at', 'cached_full_text', 'cached_outline', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'protected', 'archived', 'deleted']
  - constraint: unique(full_path)
  - constraint: filename must end with '.docx' for active/protected/archived statuses
  - constraint: content_version >= 1
  - constraint: file_size_bytes is null OR file_size_bytes >= 0
- `document_blocks.json` — Persisted logical structure of a document as ordered blocks (paragraphs, headings, tables, images, page breaks). Supports add_paragraph/add_heading/add_table/add_picture/add_page_break, delete_paragraph, get_paragraph_text_from_document, and outline generation. (18 rows; fields: ['id', 'document_id', 'block_type', 'ordinal', 'status', 'text', 'paragraph_style', 'heading_level', 'table_rows', 'table_cols', 'table_data', 'image_path', 'image_width_in', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: unique(document_id, ordinal) where status='active'
  - constraint: ordinal >= 0
  - constraint: block_type='heading' implies heading_level between 1 and 9 and text is not null
- `text_spans.json` — Character-range formatting spans applied within paragraph/heading blocks, used by format_text and as a source of truth for rendering back into .docx runs. (18 rows; fields: ['id', 'document_id', 'block_id', 'start_pos', 'end_pos', 'bold', 'italic', 'underline', 'color', 'font_size', 'font_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: foreign key(block_id) references document_blocks(id) on delete cascade
  - constraint: start_pos >= 0
  - constraint: end_pos > start_pos
- `styles.json` — Custom style definitions per document for create_custom_style and as a reference for paragraph_style/base_style usage. (18 rows; fields: ['id', 'document_id', 'style_name', 'base_style_name', 'bold', 'italic', 'font_size', 'font_name', 'color', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: unique(document_id, style_name) where status='active'
  - constraint: font_size is null OR (font_size between 1 and 512)
- `notes.json` — Footnotes and endnotes attached to specific paragraph/heading blocks, including numbering style configuration to support add_footnote_to_document, add_endnote_to_document, convert_footnotes_to_endnotes_in_document, and customize_footnote_style. (18 rows; fields: ['id', 'document_id', 'block_id', 'note_type', 'note_text', 'status', 'created_at', 'updated_at', 'footnote_numbering_format', 'footnote_start_number', 'footnote_font_name', 'footnote_font_size'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: foreign key(block_id) references document_blocks(id) on delete cascade
  - constraint: block_id must reference a document_blocks row where block_type in ('paragraph','heading')
  - constraint: footnote_start_number is null OR footnote_start_number >= 1
- `table_formats.json` — Formatting metadata for table blocks, used by format_table including borders, header row handling, and optional per-cell shading grid. (18 rows; fields: ['id', 'document_id', 'table_block_id', 'has_header_row', 'border_style', 'shading', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: foreign key(table_block_id) references document_blocks(id) on delete cascade
  - constraint: table_block_id must reference a document_blocks row where block_type='table'
  - constraint: unique(table_block_id) where status='active'

## Business rules enforced by the tools

- All tool parameters named 'filename'/'source_filename'/'destination_filename' map to documents.full_path (normalized); if a filename is provided without '.docx', the service appends '.docx' before lookup/creation.
- create_document inserts a documents row with status='active', content_version=1, and directory/filename/full_path derived from the provided filename; title/author are stored as provided.
- copy_document creates a new documents row for destination and clones all active document_blocks, styles, notes, text_spans, and table_formats from the source, resetting content_version=1 and recalculating ordinals to be contiguous.
- list_available_documents queries documents where directory equals the requested directory and status in ('active','protected','archived'), returning filenames; it must not return status='deleted'.
- get_document_info reads documents metadata plus derived counts (e.g., number of blocks, tables, notes) computed from related collections; it must fail if document status='deleted'.
- Mutating tools (add_paragraph/add_heading/add_picture/add_table/add_page_break/delete_paragraph/search_and_replace/create_custom_style/format_text/format_table/protect_document/unprotect_document/add_footnote_to_document/add_endnote_to_document/convert_footnotes_to_endnotes_in_document/customize_footnote_style) must require documents.status != 'deleted' and increment documents.content_version by 1 on success.
- protect_document transitions documents.status from 'active' to 'protected' and stores protected_password_hash; it must reject protection if already protected.
- unprotect_document transitions documents.status from 'protected' to 'active' only if provided password verifies against protected_password_hash; on success, it clears protected_password_hash.
- delete_paragraph performs a soft delete: it sets document_blocks.status='deleted' for the target paragraph_index among active paragraph+heading blocks, and compacts remaining ordinals so future paragraph_index operations reflect current visible order.
- get_paragraph_text_from_document resolves paragraph_index against active paragraph+heading blocks ordered by ordinal and returns the block.text.
- format_text validates start_pos/end_pos are within the current block.text length at write time; it inserts a new active text_spans row (or supersedes prior spans per implementation) scoped to that block.
- search_and_replace updates document_blocks.text for all active paragraph+heading blocks in the document, and must also supersede any text_spans whose ranges become invalid (e.g., end_pos beyond new text length).
- find_text_in_document returns matches computed from documents.cached_full_text if last_indexed_at is recent enough; otherwise it recomputes from active blocks ordered by ordinal and updates cached_full_text/last_indexed_at.
- get_document_text returns concatenation of active paragraph+heading texts (and optionally table cell strings) in ordinal order; it must not include deleted blocks.
- get_document_outline derives a headings tree from active heading blocks using heading_level and ordinal; it may be served from documents.cached_outline when last_indexed_at is current.
- add_table requires rows >= 1 and cols >= 1; if data is provided it must match rows x cols or be rejected.
- format_table targets the Nth active table block by ordinal among tables; it upserts table_formats for that table_block_id; if shading is provided it must match the table's rows x cols.
- create_custom_style upserts styles by (document_id, style_name) with status='active'; base_style_name may refer to a built-in style name or an existing active custom style.
- add_footnote_to_document/add_endnote_to_document attach notes to the resolved block for paragraph_index; convert_footnotes_to_endnotes_in_document updates notes.note_type from 'footnote' to 'endnote' for all active notes in the document.
- customize_footnote_style stores document-level footnote settings by updating all active notes in the document with the current footnote_* snapshot values (or alternatively a single system-wide doc setting; here modeled as snapshot fields) and must validate start_number >= 1 and font_size within allowed range.
- convert_to_pdf creates/overwrites an output artifact on disk; backend may record the latest export path and timestamp by updating documents.updated_at and optionally storing output_filename in an implementation-specific extension field (not required for serving other tools).