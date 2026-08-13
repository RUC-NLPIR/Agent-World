# Excel MCP Server — local MCP environment

This backend stores Excel workbooks registered with the server, their worksheets, and structured representations of cell/range operations (read/write/format/merge/copy/delete) performed via the MCP tools. It also stores higher-level worksheet artifacts (tables, charts, pivot tables) plus formula validation/application requests, so each tool call can be persisted, audited, and replayed against the underlying file on disk/object storage.

Repository: https://github.com/haris-musa/excel-mcp-server
Homepage: https://smithery.ai/server/@haris-musa/excel-mcp-server

## Datastore

- `workbooks.json` — Registered Excel workbooks known to the service. Represents the file identity, storage location, and lifecycle (created, active, archived). Used by all tools that take a filepath. (12 rows; fields: ['id', 'filepath', 'storage_uri', 'file_hash_sha256', 'file_size_bytes', 'status', 'last_opened_at', 'last_modified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'active', 'archived', 'deleted', 'error']
  - constraint: unique(filepath) WHERE status != 'deleted'
  - constraint: file_size_bytes IS NULL OR file_size_bytes >= 0
- `worksheets.json` — Worksheets within a workbook. Supports create/copy/delete/rename operations and metadata enumeration. (18 rows; fields: ['id', 'workbook_id', 'name', 'position_index', 'visibility', 'status', 'dimension_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(workbook_id) references workbooks(id) on delete cascade
  - constraint: unique(workbook_id, name) WHERE status = 'active'
  - constraint: position_index IS NULL OR position_index >= 1
- `worksheet_objects.json` — Higher-level objects created within worksheets (native Excel tables, charts, pivot tables). Used to track creation and metadata for get_workbook_metadata and object creation tools. (14 rows; fields: ['id', 'workbook_id', 'worksheet_id', 'object_type', 'name', 'source_range', 'anchor_cell', 'config', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'active', 'deleted', 'error']
  - constraint: foreign key(workbook_id) references workbooks(id) on delete cascade
  - constraint: foreign key(worksheet_id) references worksheets(id) on delete cascade
  - constraint: unique(worksheet_id, object_type, name) WHERE name IS NOT NULL AND status = 'active'
- `range_operations.json` — Append-only log of cell/range-level operations (read, write, format, merge/unmerge, copy/delete, validate range, and retrieving validation info). Stores parameters and results for auditing and replay. Also covers formula application/validation requests as operations when scoped to a range/cell. (44 rows; fields: ['id', 'workbook_id', 'worksheet_id', 'tool_name', 'operation_scope', 'start_cell', 'end_cell', 'source_range', 'destination_start_cell', 'shift_direction', 'formula', 'format_spec', 'write_payload', 'read_preview_only', 'request_params', 'result_payload', 'error_message', 'status', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(workbook_id) references workbooks(id) on delete cascade
  - constraint: foreign key(worksheet_id) references worksheets(id) on delete set null
  - constraint: completed_at IS NULL OR started_at IS NOT NULL
  - constraint: end_cell IS NULL OR start_cell IS NOT NULL
- `data_validations.json` — Cached view of data validation rules per worksheet, as discovered by get_data_validation_info and/or read_data_from_excel. Enables fast metadata retrieval without re-parsing the file each time. (25 rows; fields: ['id', 'workbook_id', 'worksheet_id', 'applies_to_range', 'validation_type', 'operator', 'formula1', 'formula2', 'allow_blank', 'show_input_message', 'input_title', 'input_message', 'show_error_message', 'error_style', 'error_title', 'error_message', 'source_operation_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'stale', 'deleted']
  - constraint: foreign key(workbook_id) references workbooks(id) on delete cascade
  - constraint: foreign key(worksheet_id) references worksheets(id) on delete cascade
  - constraint: foreign key(source_operation_id) references range_operations(id) on delete set null
  - constraint: unique(worksheet_id, applies_to_range, validation_type, coalesce(operator,''), coalesce(formula1,''), coalesce(formula2,'')) WHERE status != 'deleted'

## Business rules enforced by the tools

- create_workbook creates a workbooks row with status='creating', then must transition to 'active' only after the file exists at storage_uri and file_hash_sha256 is computed; on failure it transitions to 'error' with error details stored in a range_operations row for that call.
- All tools that accept a filepath must resolve it to exactly one non-deleted workbooks row; if none exists, the call must either fail (most tools) or create/register the workbook only via create_workbook.
- Worksheet names must be unique per workbook among active sheets; rename_worksheet must enforce unique(workbook_id, name) and reject names that collide with an existing active worksheet.
- delete_worksheet must set worksheets.status='deleted' and must not physically remove historical range_operations; subsequent operations referencing a deleted worksheet must fail unless the tool is get_workbook_metadata.
- copy_worksheet creates a new worksheets row in the same workbook with status='active' and a distinct name; it must preserve worksheet_objects by copying them with new ids and status='creating'->'active' once written to the file.
- read_data_from_excel must record start_cell (default 'A1') and optionally end_cell; if end_cell is not provided and auto-expansion is used, the resolved end_cell must be stored into result_payload for auditability.
- validate_excel_range must verify A1 notation and that start_cell/end_cell define a non-empty rectangular range; it records status='succeeded' only if the range is valid for the target worksheet dimensions.
- merge_cells and unmerge_cells must only succeed when the target range is valid; merge_cells must reject ranges that partially overlap an existing merged region unless the underlying Excel engine supports it and the result is deterministic.
- write_data_to_excel is allowed to write formulas without validation; however, the operation must still store the raw payload in request_params and mark status='failed' if the file write fails.
- validate_formula_syntax must not mutate workbook content; it records an operation with operation_scope='cell' (or 'range' if provided) and stores parse/validation outcome in result_payload.
- apply_formula must store the formula string and the target cell/range in range_operations; if the formula is invalid, the operation must fail and must not partially apply changes (atomic write requirement at the file level).
- format_range must store format_spec and target range; it must validate format_spec keys against a server-allowed whitelist (e.g., font, fill, alignment, number_format, border) before applying.
- create_table/create_chart/create_pivot_table must create a worksheet_objects row with status='creating' and transition it to 'active' only after the object is confirmed in the workbook file; on error set status='error' and keep the operation failed with error_message.
- get_workbook_metadata must return sheets (from worksheets where status='active') and may include worksheet_objects where status='active'; it must refresh worksheets.dimension_ref opportunistically when the workbook hash changed.
- get_data_validation_info must upsert data_validations for the worksheet and mark prior cached rules as 'stale' when workbooks.file_hash_sha256 changes; it must set new/updated rules to status='current'.