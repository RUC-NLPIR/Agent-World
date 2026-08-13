# RunPod — local MCP environment

This backend stores RunPod customer resources for GPU compute: Pods (compute instances), Endpoints (serverless/inference deployments), reusable Templates, attachable Network Volumes, and Container Registry Auth credentials used to pull private images. Core workflows are CRUD on these resources plus lifecycle actions on Pods (start/stop) and safe deletion with referential integrity across attachments and image auth usage.

Repository: https://github.com/runpod/runpod-mcp-ts
Homepage: https://smithery.ai/server/@runpod/runpod-mcp-ts

## Datastore

- `pods.json` — User-deployed compute Pods (GPU instances) with lifecycle controls (start/stop/delete) and configuration (image, GPU type, networking, mounts). (20 rows; fields: ['id', 'name', 'template_id', 'container_registry_auth_id', 'image', 'gpu_type', 'gpu_count', 'vcpu_count', 'memory_gb', 'disk_gb', 'expose_http', 'ports', 'env', 'status', 'desired_status', 'provider_region', 'public_ip', 'ssh_connection', 'billing_hourly_usd', 'last_started_at', 'last_stopped_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'running', 'stopped', 'stopping', 'starting', 'error', 'deleted']
  - constraint: unique(name) WHERE deleted_at IS NULL
  - constraint: gpu_count >= 1 AND gpu_count <= 64
  - constraint: vcpu_count IS NULL OR (vcpu_count >= 1 AND vcpu_count <= 512)
  - constraint: memory_gb IS NULL OR (memory_gb >= 1 AND memory_gb <= 4096)
- `endpoints.json` — Serverless/inference endpoints. Stores deployment configuration, scaling settings, and current status. (19 rows; fields: ['id', 'name', 'template_id', 'container_registry_auth_id', 'image', 'gpu_type', 'min_workers', 'max_workers', 'idle_timeout_seconds', 'env', 'status', 'url', 'auth_mode', 'request_schema', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['deploying', 'active', 'updating', 'error', 'deleted']
  - constraint: unique(name) WHERE deleted_at IS NULL
  - constraint: min_workers >= 0 AND min_workers <= 1000
  - constraint: max_workers >= 0 AND max_workers <= 1000
  - constraint: max_workers >= min_workers
- `templates.json` — Reusable deployment templates for Pods/Endpoints including image, env, and resource defaults. (18 rows; fields: ['id', 'name', 'description', 'kind', 'default_image', 'default_env', 'default_gpu_type', 'default_gpu_count', 'default_disk_gb', 'default_ports', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(name) WHERE deleted_at IS NULL
  - constraint: default_gpu_count IS NULL OR (default_gpu_count >= 1 AND default_gpu_count <= 64)
  - constraint: default_disk_gb IS NULL OR (default_disk_gb >= 1 AND default_disk_gb <= 10000)
- `network_volumes.json` — Network-attached persistent volumes. May be attached to Pods via mounts stored on the pod record. (18 rows; fields: ['id', 'name', 'region', 'size_gb', 'filesystem', 'mounts', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'in_use', 'updating', 'error', 'deleted']
  - constraint: unique(name) WHERE deleted_at IS NULL
  - constraint: size_gb >= 1 AND size_gb <= 65536
  - constraint: mounts IS NULL OR (json_array_length(mounts) >= 0)
  - constraint: filesystem IN ('ext4','xfs')
- `container_registry_auths.json` — Stored container registry credentials used to pull private images for Pods/Endpoints/Templates. (18 rows; fields: ['id', 'name', 'registry', 'username', 'credential_type', 'secret_ciphertext', 'secret_last4', 'status', 'last_validated_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'deleted']
  - constraint: unique(name) WHERE deleted_at IS NULL
  - constraint: unique(registry, username) WHERE deleted_at IS NULL
  - constraint: credential_type IN ('password','token','json_key')
  - constraint: secret_ciphertext <> ''

## Business rules enforced by the tools

- list-pods returns pods where deleted_at IS NULL; delete-pod sets status='deleted' and deleted_at, and must prevent further start/stop/update operations.
- get-pod retrieves by pods.id and must not return secret material; if deleted_at IS NOT NULL it is either hidden or returned with status='deleted' depending on API policy.
- create-pod must set status='provisioning' and may set template_id; if template_id is provided, default_* fields from templates are applied when explicit pod fields are absent.
- update-pod may only modify mutable configuration fields (e.g., name, env, ports, disk_gb within limits) when pods.status IN ('stopped','running'); changes that require reprovisioning must set desired_status and transition through 'updating' is not allowed because pod lifecycle uses stopping/starting.
- start-pod is only valid when status='stopped' or (status='error' and the provider supports restart); it sets desired_status='running' and transitions 'stopped'->'starting'->'running' asynchronously.
- stop-pod is only valid when status='running' (or 'error' if provider supports); it sets desired_status='stopped' and transitions 'running'->'stopping'->'stopped' asynchronously.
- delete-pod is invalid if status is already 'deleted'; it must detach any network volume mounts in pods.ports/env do not apply; mounted volumes are represented on network_volumes.mounts and must have pod_id removed before final deletion completes.
- list-endpoints returns endpoints where deleted_at IS NULL; delete-endpoint soft-deletes and transitions status to 'deleted'.
- create-endpoint must enforce max_workers >= min_workers and status='deploying' initially; once ready it becomes 'active' and url is set.
- update-endpoint transitions 'active'->'updating' and must return to 'active' or 'error'; changing image/template/env/scaling fields updates updated_at and may redeploy.
- Templates can be created/updated/deleted; delete-template sets status='deleted' and deleted_at, but existing pods/endpoints referencing the template_id remain valid (template_id becomes historical reference; hard delete is not allowed).
- Network volumes cannot be deleted while status='in_use' unless mounts array is empty; delete-network-volume must verify no active mounts remain.
- update-network-volume may only allow size increases (size_gb can increase, never decrease) and transitions through status='updating'.
- Container registry auth secrets are stored encrypted in secret_ciphertext and must never be returned by list-container-registry-auths/get-container-registry-auth; only metadata (name, registry, username, credential_type, status, timestamps) is returned.
- delete-container-registry-auth sets status='deleted' and deleted_at and must be rejected if any non-deleted pod or endpoint references it via container_registry_auth_id (or must first set those references to NULL).
- Uniqueness constraints for names apply only for non-deleted records (deleted_at IS NULL).