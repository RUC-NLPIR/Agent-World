# Claude Custom Prompts — local MCP environment

This backend stores a library of reusable Claude prompt templates (including optional system messages), their declared arguments, and optional multi-step prompt chains. It also records operational events for updates/deletes/reloads and logs executions of slash commands so the service can render templates, track usage, and safely apply lifecycle rules (draft/active/archived/deleted).

Repository: https://github.com/minipuft/claude-prompts-mcp
Homepage: https://smithery.ai/server/@minipuft/claude-prompts-mcp

## Datastore

- `prompts.json` — Prompt templates users can invoke via slash/>> commands. Supports both single prompts and chain prompts. Soft-delete is used so prompt IDs remain referentially stable for logs and chains. (18 rows; fields: ['id', 'command_name', 'name', 'category', 'description', 'system_message', 'user_message_template', 'is_chain', 'status', 'version', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'archived', 'deleted']
  - constraint: unique(command_name) where status != 'deleted'
  - constraint: name != ''
  - constraint: category != ''
  - constraint: description != ''
- `prompt_arguments.json` — Declared arguments accepted by a prompt template. Used to validate slash-command invocations and to render templates safely. (33 rows; fields: ['id', 'prompt_id', 'name', 'description', 'required', 'position', 'created_at', 'updated_at'])
  - constraint: foreign key(prompt_id) references prompts(id) on delete restrict
  - constraint: unique(prompt_id, name)
  - constraint: position >= 1
  - constraint: name != ''
- `prompt_chain_steps.json` — Steps for chain prompts. Each step references a prompt to execute, and provides input/output mappings to wire chain inputs/outputs to step arguments and results. (26 rows; fields: ['id', 'chain_prompt_id', 'step_index', 'step_name', 'prompt_id', 'input_mapping', 'output_mapping', 'created_at', 'updated_at'])
  - constraint: foreign key(chain_prompt_id) references prompts(id) on delete restrict
  - constraint: foreign key(prompt_id) references prompts(id) on delete restrict
  - constraint: unique(chain_prompt_id, step_index)
  - constraint: unique(chain_prompt_id, step_name)
- `prompt_sections.json` — Normalized editable sections for a prompt to support modify_prompt_section. Canonical sections mirror the tool's allowed values plus arbitrary custom sections. (30 rows; fields: ['id', 'prompt_id', 'section_name', 'content', 'is_canonical', 'created_at', 'updated_at'])
  - constraint: foreign key(prompt_id) references prompts(id) on delete restrict
  - constraint: unique(prompt_id, section_name)
  - constraint: section_name != ''
  - constraint: content can be empty only for System Message (enforced at write time)
- `prompt_events.json` — Append-only operational log for executions and admin mutations. Supports auditing, debugging, and restart/reload tracking. (33 rows; fields: ['id', 'event_type', 'prompt_id', 'raw_command', 'command_name', 'arguments_json', 'filter_text', 'section_name', 'restart_requested', 'reason', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'applied', 'failed']
  - constraint: restart_requested in (true,false)
  - constraint: event_type='command_processed' implies raw_command is not null
  - constraint: event_type in ('prompt_updated','prompt_deleted','prompt_section_modified') implies prompt_id is not null
  - constraint: status='failed' implies error_message is not null

## Business rules enforced by the tools

- process_slash_command must parse the incoming command string into (command_name, freeform input/args) and resolve it to exactly one prompts.command_name with status='active'; if none found, the tool returns a not-found error and records a prompt_events row with status='failed'.
- listprompts returns prompts where status in ('active','archived','draft') and (filter_text is null/empty OR command_name ILIKE %filter_text% OR name ILIKE %filter_text% OR description ILIKE %filter_text%); it must not return status='deleted' prompts.
- update_prompt(id, ...) upserts the prompt row by id; it must set prompts.name/category/description/system_message/user_message_template/is_chain and replace all prompt_arguments for that prompt in a single transaction.
- update_prompt must enforce unique(prompts.command_name) among non-deleted prompts; if the incoming payload implies a command_name change, the change must be rejected if it would collide.
- update_prompt with isChain=true must replace prompt_chain_steps with the provided chainSteps (or empty array); with isChain=false it must delete any existing prompt_chain_steps for that prompt.
- For chain steps, every chainSteps[].promptId must reference an existing prompts.id with status in ('active','archived','draft'); referencing a deleted prompt is rejected.
- modify_prompt_section must upsert prompt_sections(prompt_id, section_name) with content=new_content, and must also keep prompts fields in sync for canonical sections: title->prompts.name, description->prompts.description, 'System Message'->prompts.system_message, 'User Message Template'->prompts.user_message_template.
- delete_prompt(id) must soft-delete by setting prompts.status='deleted' and prompts.deleted_at=now(); it must not physically delete rows referenced by prompt_events or by other chains; if other chain steps reference this prompt, deletion is rejected unless those references are removed first.
- Any tool call with restartServer=true (or reload_prompts.restart=true) must create a prompt_events row with event_type='server_restart_requested' (and also the underlying mutation event) and restart_requested=true; the operational side may transition the event status from recorded->applied/failed asynchronously.
- reload_prompts must create a prompt_events row with event_type='prompts_reloaded', capturing restart flag and reason; if restart=true, it must also create server_restart_requested.
- All mutations (update_prompt, delete_prompt, modify_prompt_section, reload_prompts) must update prompts.updated_at and increment prompts.version when prompt content/structure changes.