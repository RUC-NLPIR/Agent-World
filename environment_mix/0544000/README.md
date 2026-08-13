# Drawing Tool for AI Assistants — local MCP environment

This backend stores drawing canvases and the operations applied to them (e.g., filling rectangles) so the current canvas state can be retrieved either as raw pixel JSON or rendered PNG (base64). The main workflow is: create a canvas, apply one or more drawing operations, then read the latest canvas image/data; the system keeps an append-only operation log for reproducibility and debugging.

Repository: https://github.com/flrngel/mcp-painter
Homepage: https://smithery.ai/server/@flrngel/mcp-painter

## Datastore

- `canvas_sessions.json` — A logical drawing session that holds the current active canvas for a client/assistant and tracks its lifecycle. (18 rows; fields: ['id', 'status', 'active_canvas_id', 'client_key', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed']
  - constraint: status in ('active','closed')
  - constraint: active_canvas_id references canvases(id) on update cascade on delete set null
- `canvases.json` — A bitmap canvas with fixed dimensions and a current render pointer. Created by drawing_generateCanvas. (19 rows; fields: ['id', 'session_id', 'status', 'width_px', 'height_px', 'background_rgba', 'operation_seq', 'current_render_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'rendering', 'failed', 'archived']
  - constraint: session_id references canvas_sessions(id) on delete cascade
  - constraint: width_px between 1 and 16384
  - constraint: height_px between 1 and 16384
  - constraint: operation_seq >= 0
- `canvas_operations.json` — Append-only log of drawing operations applied to a canvas (e.g., fillRectangle). Enables deterministic replay and auditing. (18 rows; fields: ['id', 'canvas_id', 'seq', 'op_type', 'status', 'x', 'y', 'width', 'height', 'color_rgba', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'applied', 'rejected']
  - constraint: canvas_id references canvases(id) on delete cascade
  - constraint: unique(canvas_id, seq)
  - constraint: seq >= 1
  - constraint: op_type in ('fill_rectangle')
- `canvas_renders.json` — Materialized render outputs for a canvas at a given operation sequence: base64 PNG plus optional raw pixel data reference for JSON retrieval. (19 rows; fields: ['id', 'canvas_id', 'status', 'op_seq', 'png_base64', 'pixel_data_json', 'content_sha256', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'building', 'failed']
  - constraint: canvas_id references canvases(id) on delete cascade
  - constraint: op_seq >= 0
  - constraint: unique(canvas_id, op_seq)
  - constraint: If status='ready' then png_base64 is not null

## Business rules enforced by the tools

- drawing_generateCanvas(width,height) creates a new canvases row with width_px=width, height_px=height, status='ready', operation_seq=0, and creates an initial canvas_renders row for op_seq=0 with status='ready'; it also sets canvas_sessions.active_canvas_id to the new canvas (creating an active session if the service maintains a default session).
- drawing_fillRectangle(x,y,width,height,color) requires an active canvas; it inserts a canvas_operations row with op_type='fill_rectangle' and next seq=canvases.operation_seq+1, normalizing color.a to 255 when omitted, and updates canvases.operation_seq atomically.
- After a successful fillRectangle operation is applied, a new canvas_renders row must be created (or scheduled) for (canvas_id, op_seq=canvases.operation_seq). Canvases.current_render_id must point to the latest successful render for fast reads.
- drawing_getCanvasPng reads canvases.current_render_id -> canvas_renders.png_base64 and returns it; if the latest render is missing or not ready, the service must either block until ready or return the most recent ready render (must be consistent behavior).
- drawing_getCanvasData reads canvases.current_render_id -> canvas_renders.pixel_data_json; if pixel_data_json is not stored, the service must regenerate it from operations or from an internal pixel buffer and then persist it in canvas_renders.
- Coordinate and size inputs are validated: width and height must be > 0; color channels r,g,b,a must be integers in [0,255]; invalid operations are recorded with status='rejected' and an error_message, and must not advance canvases.operation_seq.
- Concurrency control: multiple fillRectangle calls against the same canvas must not produce duplicate (canvas_id, seq) and must serialize operation_seq updates (e.g., via row-level locking or optimistic concurrency on operation_seq).
- Quota/limits: maximum canvas pixels (width_px*height_px) must not exceed 67,108,864 (e.g., 8192x8192) and maximum stored pixel_data_json size must be enforced; requests exceeding limits are rejected and logged as rejected operations (or rejected canvas creation).