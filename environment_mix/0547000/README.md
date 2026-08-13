# Linode MCP Server — local MCP environment

This backend models a Linode account control-plane for an MCP server: compute instances (with configs/disks), networking and security constructs (IPs, firewalls, VLAN/VPC), plus managed services (Object Storage, Domains/DNS, Databases, Kubernetes). The main workflows are CRUD + lifecycle actions (boot/reboot/shutdown/resize/attach/detach/assign) executed as asynchronous operations, with resources transitioning through well-defined status states.

Repository: https://github.com/takashito/linode-mcp-server
Homepage: https://smithery.ai/server/@takashito/linode-mcp-server

## Datastore

- `linode_instances.json` — Core compute instances (Linodes) plus their child resources needed by instance/config/disk/stats/kernels/types actions. (22 rows; fields: ['id', 'label', 'region_id', 'type_id', 'kernel_id', 'image_id', 'placement_group_id', 'backups_enabled', 'tags', 'status', 'last_operation_id', 'created_at', 'updated_at', 'deleted_at', 'configs', 'disks', 'stats_timeseries'])
  - lifecycle `status`: ['provisioning', 'running', 'offline', 'rebooting', 'shutting_down', 'booting', 'resizing', 'cloning', 'rebuilding', 'rescuing', 'deleting', 'deleted', 'error']
  - constraint: unique(label, region_id) WHERE deleted_at IS NULL
  - constraint: configs[*].config_id unique within instance
  - constraint: disks[*].disk_id unique within instance
  - constraint: disks[*].size_mb >= 256
- `storage_dns_managed.json` — Non-compute managed resources: Block Storage volumes, Object Storage buckets/keys/certs, Domains and DNS records, and Managed Database instances (MySQL/PostgreSQL) with credentials and certificates. (19 rows; fields: ['id', 'resource_type', 'label', 'region_id', 'status', 'spec', 'attachments', 'parent_id', 'secrets', 'last_operation_id', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['provisioning', 'active', 'updating', 'suspending', 'suspended', 'resizing', 'deleting', 'deleted', 'error']
  - constraint: If resource_type='volume' then spec.size_gb between 10 and 10240 and region_id not null
  - constraint: If resource_type='volume' then attachments length <= 1
  - constraint: If resource_type='object_bucket' then unique(spec.bucket_name, region_id) WHERE deleted_at IS NULL
  - constraint: If resource_type='domain' then unique(spec.domain_name) WHERE deleted_at IS NULL
- `network_security.json` — Networking and security resources: IP addresses + IPv6 pools/ranges, Firewalls (rules and device attachments), VLANs, VPCs and subnets, NodeBalancers and their configs/nodes, and Placement Groups. (19 rows; fields: ['id', 'resource_type', 'region_id', 'status', 'label', 'parent_id', 'instance_id', 'spec', 'last_operation_id', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['provisioning', 'active', 'updating', 'deleting', 'deleted', 'error']
  - constraint: If resource_type='ip_address' then unique(spec.address) WHERE deleted_at IS NULL
  - constraint: If resource_type='ip_address' then spec.version in (4,6)
  - constraint: If resource_type='ip_address' then spec.rdns is either null or a valid hostname
  - constraint: If resource_type='firewall' then spec.rules.inbound and spec.rules.outbound are arrays of rule objects; max 256 rules each
- `kubernetes.json` — Kubernetes clusters, node pools, and node-level records supporting cluster CRUD, node pool CRUD, recycle/delete node(s), kubeconfig/service token and dashboard URL retrieval. (19 rows; fields: ['id', 'entity_type', 'parent_id', 'label', 'region_id', 'k8s_version', 'type_id', 'count', 'status', 'api_endpoints', 'access', 'spec', 'last_operation_id', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['provisioning', 'running', 'updating', 'recycling', 'deleting', 'deleted', 'error', 'suspended']
  - constraint: If entity_type='cluster' then region_id not null and label not null
  - constraint: If entity_type='node_pool' then parent_id required and must reference a cluster; type_id not null; count between 1 and 500
  - constraint: If entity_type='node' then parent_id required and must reference a node_pool
  - constraint: k8s_version must be in infra_catalog.spec.available_k8s_versions when set
- `infra_catalog.json` — Read-mostly catalog of provider-offered items used by list/get tools: regions, instance types, kernels, database engines/types, kubernetes versions/types, and object storage clusters. (17 rows; fields: ['id', 'catalog_type', 'status', 'label', 'spec', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'unavailable']
  - constraint: unique(catalog_type, (spec.slug))
  - constraint: If catalog_type='region' then spec.country and spec.capabilities present
  - constraint: If catalog_type='linode_type' then spec.vcpus >= 1 and spec.memory_mb >= 1024 and spec.disk_mb >= 25600
- `operations.json` — Asynchronous action ledger for mutating tools (boot/reboot/shutdown/resize/clone/rebuild/rescue, attach/detach, firewall rule updates, k8s recycle/upgrade, db suspend/resume/patch, etc.). (21 rows; fields: ['id', 'resource_collection', 'resource_id', 'operation_type', 'status', 'request', 'result', 'error_message', 'created_at', 'updated_at', 'started_at', 'finished_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: resource_id must exist in resource_collection at operation creation time (except create where result contains new id)
  - constraint: If status in ('succeeded','failed','cancelled') then finished_at not null
  - constraint: If status='running' then started_at not null
  - constraint: Only one running operation per (resource_collection, resource_id)

## Business rules enforced by the tools

- All delete_* tools perform soft delete by setting deleted_at and transitioning status to deleting -> deleted via an operation; read tools must exclude deleted_at IS NOT NULL unless explicitly fetching by id for audit purposes.
- Instance power actions enforce state: boot only allowed from offline; shutdown only from running; reboot only from running; rescue allowed only from offline/running but results in rescuing state and requires a kernel/rescue spec in operation.request.
- resize_instance requires the target type_id to be an active infra_catalog item of catalog_type='linode_type'; disk sizes may not exceed the destination plan's disk_mb (from infra_catalog.spec).
- clone_instance creates a new linode_instances row and an operation of type clone; the source instance must not be deleted and must be in running or offline.
- Volume attach/detach enforce single attachment: a volume with attachments length=1 cannot be attached again; detach requires the instance_id to match the attachment entry.
- update_ip_address only allows changing reverse DNS (spec.rdns); allocate_ip creates a new ip_address and associates instance_id; share_ips creates an operation whose request includes source and target instance ids and a list of ip ids that must all be active and currently attached to the source.
- Firewall rules update is atomic: update_firewall_rules replaces the entire ruleset in network_security.spec.rules and creates an operation; rule validation enforces protocol/port/cidr correctness and a max of 256 inbound and 256 outbound rules.
- NodeBalancer hierarchy integrity: configs and nodes cannot exist without their parent; deleting a nodebalancer cascades soft-delete to configs and nodes (same operation id for audit).
- Placement group assign/unassign modifies linode_instances.placement_group_id via operations; an instance may belong to at most one placement group at a time; placement group and instance must share the same region_id.
- VPC subnet CIDRs must not overlap within the same VPC; update_vpc_subnet must preserve non-overlap; delete_vpc must soft-delete subnets first (enforced by operation ordering).
- Object storage bucket names are unique per region; bucket access defaults are stored in storage_dns_managed where resource_type='object_bucket' under spec.default_access; per-bucket access in spec.access.
- upload_object_storage_bucket_certificate stores encrypted cert/key in storage_dns_managed.secrets for resource_type='object_bucket_certificate' whose parent_id points to the bucket; delete_object_storage_bucket_certificate removes that child resource and clears any bucket spec.certificate_ref.
- Database credential tools: get_*_credentials returns decrypted secrets; reset_*_credentials rotates secrets and sets secrets.rotated_at, creating an operation of type reset_credentials; suspend/resume/patch transition db status according to lifecycle rules.
- Kubernetes kubeconfig/service token/dashboard URL are stored encrypted in kubernetes.access and only returned by their respective get_* tools; delete_kubernetes_service_token clears encrypted_service_token and records an operation.
- Catalog list/get tools (regions, kernels, instance types, db engines/types, kubernetes versions/types, object storage clusters) are served exclusively from infra_catalog; resources referencing catalog items must point to status='active' items at create time.