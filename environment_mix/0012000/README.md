# Image Generation Server — local MCP environment

This backend stores image generation jobs submitted to an Image Generation Server and the resulting generated images/artifacts. The primary workflow is: create a generation job, run it to produce one or more images, store outputs with metadata, and allow operational auditing of job status and server-side parameters used.

Repository: https://github.com/GongRzhe/Image-Generation-MCP-Server
Homepage: https://smithery.ai/server/@GongRzhe/Image-Generation-MCP-Server

## Datastore

- `gen_jobs.json` — Top-level image generation requests/jobs. Each job represents one invocation of the generate_image tool and tracks lifecycle, server-side parameters, and execution metrics. (18 rows; fields: ['id', 'status', 'requested_via_tool', 'input_payload', 'server_parameters', 'idempotency_key', 'started_at', 'finished_at', 'error_code', 'error_message', 'compute_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: status IN ('queued','running','succeeded','failed','cancelled')
  - constraint: requested_via_tool = 'generate_image'
  - constraint: unique(idempotency_key) WHERE idempotency_key IS NOT NULL
  - constraint: compute_ms IS NULL OR compute_ms >= 0
- `gen_artifacts.json` — Artifacts produced by generation jobs (usually images, but can also include masks, thumbnails, or metadata blobs). (18 rows; fields: ['id', 'job_id', 'artifact_type', 'status', 'mime_type', 'byte_size', 'width', 'height', 'storage_provider', 'storage_bucket', 'storage_key', 'sha256', 'sequence_index', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'available', 'deleted']
  - constraint: foreign key(job_id) references gen_jobs(id) on delete cascade
  - constraint: artifact_type IN ('image','thumbnail','mask','metadata')
  - constraint: status IN ('pending','available','deleted')
  - constraint: sequence_index >= 0
- `server_runs.json` — Operational runs/executions of the server worker process used to execute queued generation jobs. Supports auditing, crash recovery, and associating jobs with a run instance. (18 rows; fields: ['id', 'status', 'hostname', 'pid', 'version', 'started_at', 'last_heartbeat_at', 'stopped_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['starting', 'healthy', 'degraded', 'stopped', 'crashed']
  - constraint: status IN ('starting','healthy','degraded','stopped','crashed')
  - constraint: pid IS NULL OR pid > 0
  - constraint: stopped_at IS NULL OR stopped_at >= started_at
  - constraint: last_heartbeat_at IS NULL OR last_heartbeat_at >= started_at
- `job_executions.json` — Associates a generation job with a particular server run attempt, tracking retries and execution outcomes. (18 rows; fields: ['id', 'job_id', 'run_id', 'attempt_number', 'status', 'assigned_at', 'started_at', 'finished_at', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['assigned', 'running', 'succeeded', 'failed', 'abandoned']
  - constraint: foreign key(job_id) references gen_jobs(id) on delete cascade
  - constraint: foreign key(run_id) references server_runs(id) on delete restrict
  - constraint: attempt_number >= 1
  - constraint: unique(job_id, attempt_number)

## Business rules enforced by the tools

- Calling generate_image must create exactly one gen_jobs row with requested_via_tool='generate_image' and input_payload equal to the received tool parameters (currently {}).
- A gen_jobs row begins in status='queued' and may only transition according to the defined lifecycle transitions.
- When a worker claims a queued job, it must create a job_executions row with attempt_number = (max previous attempt_number + 1) for that job, set status='assigned', and then transition to 'running' when started.
- A gen_jobs row must not transition to 'succeeded' unless at least one gen_artifacts row exists for that job with status='available' and artifact_type='image'.
- If a job finishes with status='failed', gen_jobs.error_code and gen_jobs.error_message must be set, and finished_at must be non-null.
- gen_artifacts must be created with status='pending' before binary content is finalized; it may transition to 'available' only once storage_provider/storage_key are set and (if present) sha256 is a 64-character hex string.
- sequence_index must be unique per (job_id, artifact_type) to guarantee deterministic ordering of multiple outputs.
- If idempotency_key is provided and a non-terminal job exists with the same key, the server must return the existing job rather than creating a new one; if a terminal job exists, behavior must be consistent (either return the existing result or create a new job) and enforced uniformly.
- On deletion/cancellation semantics: cancelling a queued or running job sets gen_jobs.status='cancelled'; any pending artifacts for that job must be transitioned to 'deleted' (soft delete) rather than physically removed.
- server_runs.status='healthy' requires last_heartbeat_at to be within an operational threshold (e.g., 60s) of current time; otherwise the run must be marked 'degraded' or 'crashed' and any running job_executions on that run must be marked 'abandoned'.