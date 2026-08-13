# Memory Bank — local MCP environment

Memory Bank stores a workspace-scoped, file-backed knowledge base plus structured logs (progress updates and decisions) used by an MCP agent. The main workflows are initializing/selecting a memory-bank root path, reading/writing/listing managed files, tracking progress (optionally updating active context), logging decisions, and running one-off maintenance operations like filename migration and UMB command processing/completion.

Repository: https://github.com/aakarsh-sasi/memory-bank-mcp
Homepage: https://smithery.ai/server/@aakarsh-sasi/memory-bank-mcp

## Datastore

- `memory_banks.json` — Represents a single Memory Bank instance rooted at a filesystem path, including current mode, initialization state, and configuration used by the MCP server. (12 rows; fields: ['id', 'root_path', 'status', 'current_mode', 'active_context_file_id', 'mcp_config', 'last_error', 'initialized_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['uninitialized', 'initializing', 'ready', 'error', 'archived']
  - constraint: unique(root_path) -- only one memory bank per root path
  - constraint: root_path <> ''
  - constraint: current_mode in ('architect','ask','code','debug','test')
  - constraint: status='ready' implies initialized_at is not null
- `memory_bank_files.json` — Managed files inside a Memory Bank (content-addressed by path/filename), used for read/write/list, active context, and migration from camelCase to kebab-case. (20 rows; fields: ['id', 'memory_bank_id', 'filename', 'relative_path', 'content', 'content_sha256', 'status', 'naming_convention', 'last_read_at', 'last_written_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'renaming', 'deleted']
  - constraint: unique(memory_bank_id, relative_path)
  - constraint: filename <> ''
  - constraint: relative_path <> ''
  - constraint: naming_convention in ('unknown','camelCase','kebab-case')
- `progress_entries.json` — Structured progress log entries created by track_progress. These may also drive updates to the active context content. (21 rows; fields: ['id', 'memory_bank_id', 'action', 'description', 'update_active_context', 'active_context_snapshot', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'applied', 'failed']
  - constraint: action <> ''
  - constraint: description <> ''
- `decision_log_entries.json` — Decision log entries created by log_decision and typically rendered into a decision log file. (12 rows; fields: ['id', 'memory_bank_id', 'title', 'context', 'decision', 'alternatives', 'consequences', 'status', 'rendered_file_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['logged', 'rendered', 'retracted']
  - constraint: title <> ''
  - constraint: context <> ''
  - constraint: decision <> ''
- `operations.json` — Audit and state tracking for long-ish or multi-step actions: initialize, set path, debug config, migrate naming, process UMB command, complete UMB, and mode switching. (36 rows; fields: ['id', 'memory_bank_id', 'operation_type', 'status', 'request_params', 'result_summary', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: completed_at is null or started_at is not null
  - constraint: status in ('queued','running','succeeded','failed','cancelled')
  - constraint: operation_type in ('initialize_memory_bank','set_memory_bank_path','debug_mcp_config','read_memory_bank_file','write_memory_bank_file','list_memory_bank_files','get_memory_bank_status','migrate_file_naming','track_progress','update_active_context','log_decision','switch_mode','get_current_mode','process_umb_command','complete_umb')

## Business rules enforced by the tools

- initialize_memory_bank(path) MUST upsert a memory_banks row for root_path=path; if it is new, status transitions uninitialized->initializing->ready and initialized_at is set on success; if already ready, it MUST be idempotent (no duplicate banks due to unique(root_path)).
- set_memory_bank_path(path?) MUST select the active memory bank context by root_path; if path is omitted, it MUST resolve to the server's current working directory and use that as root_path.
- read_memory_bank_file(filename) MUST resolve filename to memory_bank_files.relative_path within the selected memory_bank_id and only return rows with status='active'; it MUST update last_read_at.
- write_memory_bank_file(filename, content) MUST upsert memory_bank_files by (memory_bank_id, relative_path=filename), set content and content_sha256, set status='active', and update last_written_at.
- list_memory_bank_files(dummy) MUST return all memory_bank_files for the selected memory_bank_id with status='active', ordered by relative_path.
- get_memory_bank_status(dummy) MUST return memory_banks.status plus a derived readiness indicator: ready only if status='ready' and at least one managed file exists or initialization has completed (initialized_at not null).
- migrate_file_naming(dummy) MUST rename only files whose naming_convention='camelCase' (or detected camelCase) to kebab-case, preserving uniqueness on (memory_bank_id, relative_path); conflicting targets MUST cause the operation to fail or skip with an explicit result_summary count.
- track_progress(action, description, updateActiveContext=true) MUST create a progress_entries row; if updateActiveContext=true it MUST also write/update the active context file (memory_banks.active_context_file_id), and set progress_entries.status to applied on success or failed with error_message on failure.
- update_active_context(tasks?, issues?, nextSteps?) MUST write an active context representation to the active context file; omitted arrays MUST be treated as 'no change' (partial update) unless the implementation explicitly chooses to overwrite, in which case it MUST record the behavior consistently in operations.request_params.
- log_decision(title, context, decision, alternatives?, consequences?) MUST insert a decision_log_entries row with status='logged' and MAY render/append it into a managed decision log file, setting rendered_file_id and status='rendered' if it does.
- switch_mode(mode) MUST validate mode in {'architect','ask','code','debug','test'} and update memory_banks.current_mode; invalid values MUST be rejected.
- get_current_mode() MUST return memory_banks.current_mode for the selected memory bank.
- process_umb_command(command) MUST create an operations row with operation_type='process_umb_command' capturing the raw command string and MUST update managed files accordingly; any file mutations MUST go through memory_bank_files upserts to maintain audit timestamps.
- complete_umb() MUST only succeed if there is a selected memory bank in status='ready' and MUST record an operations row with operation_type='complete_umb'; if completion finalizes pending steps, it MUST mark affected progress_entries from recorded->applied (or failed) deterministically.