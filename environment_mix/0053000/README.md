# Unity MCP — local MCP environment

This backend stores the state of Unity projects being controlled through an MCP server: project assets (including scripts and scenes), live scene hierarchies (GameObjects and components), Unity Editor state changes, and captured console logs. The main workflows are CRUD on assets/scripts/scenes, querying/modifying scene objects and components, executing editor/menu actions, and reading/clearing console output, all tracked as auditable operations.

Repository: https://github.com/justinpbarnett/unity-mcp
Homepage: https://smithery.ai/server/@justinpbarnett/unity-mcp

## Datastore

- `unity_projects.json` — A Unity project connected to the MCP server (one logical workspace). Holds editor-wide configuration like tags/layers, active scene, and play mode state. (12 rows; fields: ['id', 'project_name', 'project_path', 'unity_version', 'status', 'editor_state', 'active_tool_name', 'active_scene_id', 'tags', 'layers', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disconnected', 'archived']
  - constraint: unique(project_path)
  - constraint: editor_state in ('edit','play','pause')
  - constraint: json_array(tags) and json_array(layers)
  - constraint: active_scene_id references unity_scenes.id on delete set null
- `unity_assets.json` — Asset database entries for a Unity project. Covers scripts, materials, prefabs, textures, folders, scenes, etc., and supports import/create/modify/move/rename/search and preview generation metadata. (35 rows; fields: ['id', 'project_id', 'path', 'name', 'asset_type', 'guid', 'status', 'properties', 'preview_blob_ref', 'last_imported_at', 'last_modified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted', 'moved', 'importing', 'error']
  - constraint: unique(project_id, path)
  - constraint: path like 'Assets/%'
  - constraint: asset_type in ('folder','script','scene','prefab','material','texture','model','audio','animation','shader','other')
  - constraint: status != 'present' implies path is still historically retained
- `unity_scripts.json` — Specialized metadata for C# scripts (subset of unity_assets of asset_type=script). Stores source code, namespace, and script_type for script management operations. (30 rows; fields: ['id', 'project_id', 'asset_id', 'script_name', 'namespace', 'script_type', 'contents', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(project_id, script_name, namespace)
  - constraint: unique(asset_id)
  - constraint: contents != ''
  - constraint: script_type in ('MonoBehaviour','ScriptableObject','Editor','Interface','PlainClass','Other')
- `unity_scenes.json` — Scene assets plus editor/build metadata. Supports create/load/save/get_hierarchy and build-index based operations. (12 rows; fields: ['id', 'project_id', 'asset_id', 'scene_name', 'path', 'build_index', 'is_in_build', 'is_loaded', 'is_dirty', 'hierarchy_snapshot', 'status', 'last_saved_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: unique(project_id, path)
  - constraint: unique(project_id, scene_name)
  - constraint: build_index is null or build_index >= 0
  - constraint: asset_id references unity_assets.id where unity_assets.asset_type='scene'
- `unity_gameobjects.json` — Live (or last-known) scene hierarchy nodes and their component data. Supports create/modify/delete/find as well as add/remove components and set_component_property. (36 rows; fields: ['id', 'project_id', 'scene_id', 'unity_instance_id', 'name', 'path', 'parent_id', 'tag', 'layer', 'is_active', 'position', 'rotation', 'scale', 'components', 'prefab_asset_id', 'primitive_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'destroyed']
  - constraint: unique(project_id, unity_instance_id) where unity_instance_id is not null
  - constraint: unique(project_id, path) where path is not null
  - constraint: position is null or (json_array_length(position)=3)
  - constraint: rotation is null or (json_array_length(rotation)=3)
- `unity_operations_and_console.json` — Append-only operation log for tool invocations plus captured Unity console messages. Enables auditing, correlating changes, and implementing read_console(get/clear) semantics. (42 rows; fields: ['id', 'project_id', 'row_type', 'tool_name', 'action', 'request', 'result', 'status', 'started_at', 'completed_at', 'wait_for_completion', 'menu_path', 'menu_parameters', 'console_type', 'message', 'stacktrace', 'timestamp', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'recorded']
  - constraint: row_type in ('operation','console_message')
  - constraint: row_type='console_message' implies status='recorded'
  - constraint: row_type='operation' implies status in ('queued','running','succeeded','failed','cancelled')
  - constraint: tool_name is not null when row_type='operation'

## Business rules enforced by the tools

- manage_script(action='create') must create a unity_assets row with asset_type='script', status='present', path = <path>/<name>.cs (normalized), and a unity_scripts row referencing it; (project_id, path) must be unique.
- manage_script(action='read') returns unity_scripts.contents for the matching (project_id, script_name, namespace) or by derived asset path; if status='deleted' it must return not_found.
- manage_script(action='update') must update unity_scripts.contents and unity_assets.last_modified_at; script_name/namespace/script_type cannot be changed without creating a new asset path or enforcing uniqueness constraints.
- manage_script(action='delete') must transition unity_scripts.status to 'deleted' and unity_assets.status to 'deleted' atomically.
- manage_scene(action in {'create','load','save'}) must operate on unity_scenes identified by (project_id, scene_name, path); load sets is_loaded=true and sets unity_projects.active_scene_id; save sets is_dirty=false and updates last_saved_at.
- manage_scene(build_index provided) must reference a unity_scenes row where build_index matches and is_in_build=true; build_index must be >= 0.
- manage_editor(action='get_state') must reflect unity_projects.editor_state; actions 'play','pause' update editor_state with valid transitions: edit->play, play->pause, pause->play or pause->edit, play->edit.
- manage_editor(action='set_active_tool') must set unity_projects.active_tool_name to tool_name.
- manage_editor(action='add_tag') must add tag_name to unity_projects.tags if not present; tag_name must be non-empty and <= 64 chars.
- manage_editor(action='add_layer') (if implemented via layer_name) must add layer_name to unity_projects.layers if not present; layer_name must be non-empty and <= 64 chars.
- manage_gameobject(action='create') must create a unity_gameobjects row with status='present'; if save_as_prefab=true then a unity_assets row with asset_type='prefab' must exist/ be created at prefab_path (or prefab_folder/name.prefab) and unity_gameobjects.prefab_asset_id must reference it.
- manage_gameobject(action in {'modify','set_component_property'}) must locate the target using search_method ('by_name','by_id','by_path') or default targeting rules; updates must validate vector lengths for position/rotation/scale as exactly 3 floats.
- manage_gameobject(action='add_component') must insert into unity_gameobjects.components map keyed by each components_to_add entry; action='remove_component' must remove keys in components_to_remove; duplicates are no-ops.
- manage_gameobject find operations must support search_term, find_all, search_in_children, search_inactive, and search_inactive=false must exclude is_active=false rows from results.
- manage_asset(action in {'create','modify','delete','duplicate','move','rename','import'}) must mutate unity_assets.status and/or path; move/rename must preserve uniqueness (project_id, path) and record prior path by setting status='moved' on the old path or updating in-place with an operation log entry.
- manage_asset(action='search') must filter by search_pattern (path/name glob), filter_type mapping to unity_assets.asset_type, and filter_date_after against unity_assets.last_modified_at/last_imported_at; must paginate with page_size in [1,200] and page_number >= 1.
- manage_asset(action='get_components') must return derived component information: for prefab assets use unity_gameobjects.components where prefab_asset_id matches; otherwise return empty if unknown.
- read_console(action='get') must read unity_operations_and_console rows where row_type='console_message' filtered by types ('error','warning','log','all'), filter_text substring match over message/stacktrace, since_timestamp (ISO 8601) against timestamp, and limit by count (default 50, max 1000).
- read_console(action='clear') must delete or soft-delete console_message rows for the project by recording a clear operation and removing/archiving matching rows; subsequent gets must not return cleared messages.
- execute_menu_item(menu_path) must append an operation row with tool_name='execute_menu_item', menu_path, menu_parameters; action defaults to 'execute' and must be validated as 'execute' unless additional actions are supported.