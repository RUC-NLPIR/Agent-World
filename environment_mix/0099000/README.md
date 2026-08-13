# Unreal Engine Plugin — local MCP environment

This backend stores an Unreal Engine project's runtime/editor state as a set of addressable assets (materials) and in-level entities (actors/objects), along with an audit trail of tool invocations (including Python execution). The main workflows are: query current scene snapshot and counts, create/modify/delete actors in a level, create/modify/read materials by content path, and execute arbitrary Python commands while logging inputs/outputs for debugging and governance.

Repository: https://github.com/AlexKissiJr/UnrealMCP
Homepage: https://smithery.ai/server/@AlexKissiJr/unrealmcp

## Datastore

- `ue_sessions.json` — Represents a connected Unreal Engine instance/editor session that tool calls operate against. Used to scope scene queries, actor counts, and to correlate tool invocation logs. (12 rows; fields: ['id', 'status', 'engine_version', 'project_name', 'project_root', 'map_name', 'map_path', 'last_heartbeat_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['connected', 'disconnected', 'expired']
  - constraint: status in ('connected','disconnected','expired')
  - constraint: last_heartbeat_at <= updated_at OR last_heartbeat_at IS NULL
- `ue_actors.json` — Actors/objects placed in the current scene/level. Supports creation, transform modifications, deletion (soft), and counting for scene analytics. (30 rows; fields: ['id', 'session_id', 'name', 'label', 'actor_type', 'location', 'rotation', 'scale', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: FK(session_id) references ue_sessions(id) on delete cascade
  - constraint: unique(session_id, name)
  - constraint: actor_type <> ''
  - constraint: name <> ''
- `ue_materials.json` — Material assets in the Unreal project content browser, addressed by full path. Supports create, modify, and info lookup. (36 rows; fields: ['id', 'session_id', 'package_path', 'name', 'path', 'properties', 'shading_model', 'blend_mode', 'two_sided', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: FK(session_id) references ue_sessions(id) on delete cascade
  - constraint: unique(session_id, path)
  - constraint: package_path like '/Game/%'
  - constraint: path like '/Game/%'
- `ue_scene_snapshots.json` — Materialized snapshots of the current scene used to serve get_scene_info quickly and consistently. Typically created on demand and/or periodically per session. (34 rows; fields: ['id', 'session_id', 'status', 'scene_payload', 'actor_count', 'captured_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['capturing', 'ready', 'failed']
  - constraint: FK(session_id) references ue_sessions(id) on delete cascade
  - constraint: actor_count IS NULL OR actor_count >= 0
  - constraint: status='ready' implies (scene_payload IS NOT NULL AND captured_at IS NOT NULL)
  - constraint: status='failed' implies error_message IS NOT NULL
- `ue_tool_invocations.json` — Audit log of all tool calls (including execute_python, get_actor_count, and my_custom_tool), capturing parameters, results, errors, latency, and status for debugging and governance. (37 rows; fields: ['id', 'session_id', 'tool_name', 'request_params', 'status', 'result', 'error', 'started_at', 'finished_at', 'duration_ms', 'python_code', 'python_file', 'ctx', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: FK(session_id) references ue_sessions(id) on delete cascade
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at
  - constraint: tool_name='execute_python' implies (python_code IS NOT NULL OR python_file IS NOT NULL)

## Business rules enforced by the tools

- All tool calls must be associated with exactly one ue_sessions row; if the caller does not provide a session identifier, the system must resolve a single active (status='connected') session or reject the call as ambiguous.
- create_object(type, location?, label?) must insert a ue_actors row with actor_type=type, status='active'. If location is provided it must be a numeric 3-tuple; otherwise location may be NULL.
- modify_object(name, location?, rotation?, scale?) must target exactly one ue_actors row by (session_id, name) where status='active'; it must update only the provided transform fields.
- delete_object(name) must transition the targeted ue_actors row from status='active' to status='deleted' and set deleted_at; repeated deletes must be idempotent (no transition from 'deleted').
- create_material(package_path, name, properties?) must create a ue_materials row with path = package_path + '/' + name, status='active'. It must reject if (session_id, path) already exists with status='active'.
- modify_material(path, properties) must update exactly one ue_materials row by (session_id, path) where status='active'. It must merge/overwrite keys in the stored properties object; commonly extracted fields (shading_model/blend_mode/two_sided) must be synchronized when present in properties.
- get_material_info(path) must read from ue_materials by (session_id, path) where status='active' and return at minimum: name, path, shading_model, blend_mode, two_sided (nullable if unknown).
- get_scene_info must return the latest ue_scene_snapshots row for the session with status='ready'; if none exists or it is stale per server policy, a new snapshot must be created by inserting status='capturing' then transitioning to 'ready' with scene_payload and actor_count.
- get_actor_count(ctx) must record ctx in ue_tool_invocations.ctx and return either ue_scene_snapshots.actor_count (if a ready snapshot exists) or compute count of ue_actors where status='active' for the session.
- execute_python(code?, file?) must log the invocation including python_code/python_file and must enforce that at least one is non-null. The result and/or error must be captured in ue_tool_invocations, and status transitioned to 'succeeded' or 'failed' accordingly.
- my_custom_tool(ctx) must log ctx and must not mutate ue_actors or ue_materials unless explicitly implemented; any mutations must still be reflected in those collections and captured in the invocation log.
- For every tool invocation, a ue_tool_invocations row must be created with status='received' before execution and must end in exactly one terminal state: 'succeeded' or 'failed'.