# QGIS Model Context Protocol Integration — local MCP environment

This backend persists QGIS MCP server state across sessions: QGIS engine metadata, projects (loaded/created/saved), project layers, and a full audit trail of actions including processing runs, renders, and executed code. Main workflows are: start/connect (ping/info), open or create a project, manage layers and view state, run processing algorithms and ad-hoc PyQGIS code, and save/render outputs with durable logs.

Repository: https://github.com/jjsantos01/qgis_mcp
Homepage: https://smithery.ai/server/@jjsantos01/qgis_mcp

## Datastore

- `qgis_instances.json` — Represents a running QGIS MCP server instance (single-tenant engine process) and its environment metadata used by ping/get_qgis_info and as the parent context for projects and operations. (12 rows; fields: ['id', 'status', 'host', 'pid', 'qgis_version', 'qt_version', 'python_version', 'provider_registry', 'last_ping_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['starting', 'ready', 'degraded', 'stopped']
  - constraint: host is required
  - constraint: pid IS NULL OR pid > 0
  - constraint: qgis_version/qt_version/python_version length <= 64
  - constraint: last_ping_at <= updated_at OR last_ping_at IS NULL
- `projects.json` — QGIS projects created/loaded in an instance. Supports load_project, create_new_project, get_project_info, and save_project. (12 rows; fields: ['id', 'instance_id', 'status', 'file_path', 'title', 'crs_authid', 'last_saved_at', 'current_extent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'dirty', 'saving', 'closed', 'error']
  - constraint: foreign key (instance_id) references qgis_instances(id) on delete cascade
  - constraint: file_path IS NULL OR file_path like '%'
  - constraint: unique(instance_id, file_path) WHERE file_path IS NOT NULL
  - constraint: crs_authid IS NULL OR crs_authid like '%:%'
- `layers.json` — Layers belonging to a project. Supports add_vector_layer, add_raster_layer, get_layers, remove_layer, zoom_to_layer, and get_layer_features. (35 rows; fields: ['id', 'project_id', 'status', 'layer_type', 'source_path', 'provider', 'name', 'native_layer_id', 'crs_authid', 'extent', 'feature_count_estimate', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed', 'error']
  - constraint: foreign key (project_id) references projects(id) on delete cascade
  - constraint: layer_type='vector' implies provider in ('ogr','postgres','spatialite','wfs','delimitedtext') OR provider like '%'
  - constraint: layer_type='raster' implies provider in ('gdal','wms','xyz') OR provider like '%'
  - constraint: unique(project_id, native_layer_id) WHERE native_layer_id IS NOT NULL
- `layer_features_snapshots.json` — Stores retrieved feature snapshots from get_layer_features calls (bounded by limit), enabling read tools to return stable results and providing audit/debug trace without storing full datasets. (26 rows; fields: ['id', 'layer_id', 'request_limit', 'features', 'retrieved_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['complete', 'expired']
  - constraint: foreign key (layer_id) references layers(id) on delete cascade
  - constraint: request_limit between 1 and 10000
  - constraint: json array length(features) <= request_limit
  - constraint: TTL retention: mark status='expired' after 7 days
- `operations.json` — Unified audit log and job store for execute_processing, render_map, execute_code, and also records load/save/layer changes for traceability. Supports async-like lifecycle with outputs, errors, and produced artifacts paths. (37 rows; fields: ['id', 'instance_id', 'project_id', 'layer_id', 'op_type', 'status', 'request', 'result', 'artifact_path', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (instance_id) references qgis_instances(id) on delete cascade
  - constraint: foreign key (project_id) references projects(id) on delete set null
  - constraint: foreign key (layer_id) references layers(id) on delete set null
  - constraint: started_at IS NULL OR started_at >= created_at

## Business rules enforced by the tools

- There is at most one active project per qgis_instances record at a time; loading/creating a new project sets any previously active project in that instance to status='closed'.
- load_project(path) must either find an existing projects row with (instance_id, file_path=path) and set it active, or create a new projects row; in both cases it must append an operations row with op_type='load_project'.
- create_new_project(path) must fail if a projects row already exists for the same (instance_id, file_path); on success it creates the project, sets status='active', and logs an operations row.
- save_project(path=null) writes to projects.file_path when provided; if no path is provided and projects.file_path is null, the operation must fail with status='failed' and error_message explaining that a path is required for first save.
- add_vector_layer(path, provider='ogr', name=null) creates a layers row with layer_type='vector'; add_raster_layer uses layer_type='raster'. Both must mark the owning project status='dirty' upon success.
- remove_layer(layer_id) must transition layers.status from 'active'/'error' to 'removed' and must not physically delete the row; removed layers must not be returned by get_layers unless an internal debug flag is used (not part of tool surface).
- zoom_to_layer(layer_id) must verify the layer is status='active' and belongs to the current active project; on success it updates projects.current_extent to the layer extent and logs an operation.
- get_layer_features(layer_id, limit=10) is only valid for layers.layer_type='vector' and layers.status='active'; it must create a layer_features_snapshots row with request_limit=limit and store returned features truncated to the limit.
- execute_processing(algorithm, parameters) must log request/response in operations; on success it may create/update layers and must set project status to 'dirty' if the algorithm produces outputs that change the project.
- render_map(path, width=800, height=600) must validate width/height ranges and must record artifact_path=path in operations on success.
- execute_code(code) must always create an operations row; for safety, code length is capped and failures must be recorded in error_message; if code mutates the project, the project must be marked 'dirty'.
- ping and get_qgis_info must update qgis_instances.last_ping_at/updated_at and create operations rows with op_type matching the tool name for auditability.