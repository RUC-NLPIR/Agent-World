# Resume Modernizer — local MCP environment

This backend stores user-submitted resumes (raw files/text), their parsed structured representations, and the outputs of modernization operations (scoring, anonymization, ATS checks, keyword optimization, job-specific tailoring, cover letters). It also supports importing LinkedIn profile data as an alternate source, and a resource-subscription/notification mechanism to notify clients about completed processing jobs or changes.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@DynamicEndpoints/resume-modernizer-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace boundary for all resumes, LinkedIn imports, jobs, and subscriptions. Also stores basic quota/plan settings used to gate tool execution. (18 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_job_limit', 'monthly_token_limit', 'monthly_storage_mb_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_job_limit >= 0
  - constraint: monthly_token_limit >= 0
  - constraint: monthly_storage_mb_limit >= 0
- `resumes.json` — Canonical resume entity storing raw inputs, parsed structured data, generated versions, and related metadata. Most tools either create a resume, update parsed data, or create new generated variants linked here. (19 rows; fields: ['id', 'workspace_id', 'status', 'source_type', 'title', 'raw_text', 'raw_file_url', 'raw_file_mime', 'raw_file_sha256', 'parsed_resume_json', 'parsed_schema_version', 'anonymized_resume_json', 'latest_generated_resume_text', 'latest_generated_format', 'latest_cover_letter_text', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'processing', 'ready', 'archived', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, raw_file_sha256) where raw_file_sha256 is not null
  - constraint: latest_generated_format in ('text','markdown','html','docx','pdf','json') when not null
- `linkedin_profiles.json` — LinkedIn profile extracts used to seed or augment a resume. Supports both API-based extraction and non-API extraction flows. (18 rows; fields: ['id', 'workspace_id', 'status', 'method', 'profile_url', 'public_identifier', 'raw_profile_json', 'normalized_resume_json', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'processing', 'ready', 'failed', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, profile_url) where profile_url is not null
- `processing_jobs.json` — Asynchronous job ledger for all tool executions (parse, generate, score, ATS checks, conversions, etc.). Stores inputs, outputs, metrics, and links to resumes/LinkedIn profiles so every tool call has a durable record. (21 rows; fields: ['id', 'workspace_id', 'resume_id', 'linkedin_profile_id', 'tool_name', 'status', 'idempotency_key', 'input_json', 'output_json', 'error_code', 'error_message', 'cost_usd', 'prompt_tokens', 'completion_tokens', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(resume_id) references resumes(id) on delete set null
  - constraint: fk(linkedin_profile_id) references linkedin_profiles(id) on delete set null
  - constraint: cost_usd >= 0
- `resource_subscriptions.json` — Webhook/resource subscription registry for notifications about resume/job events. Powers subscribe/unsubscribe/list and test notifications. (18 rows; fields: ['id', 'workspace_id', 'status', 'resource_type', 'resource_id', 'event_types', 'endpoint_url', 'secret', 'last_notified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, resource_type, resource_id, endpoint_url)
  - constraint: endpoint_url like 'https://%' OR endpoint_url like 'http://%'
  - constraint: array_length(event_types) >= 1

## Business rules enforced by the tools

- All tool executions except list_tools must create a processing_jobs row with tool_name set to the invoked tool and status progressing via the declared lifecycle transitions.
- extract_resume must populate resumes.raw_text from resumes.raw_file_url (or equivalent upload reference stored in processing_jobs.input_json) and set resumes.status to ready on success.
- parse_resume must write resumes.parsed_resume_json and resumes.parsed_schema_version='v1'; it must not overwrite parsed data unless the request is explicitly an update operation (update_parsed_resume or apply_ats_suggestions) recorded as a job.
- generate_resume and update_resume_for_job must write resumes.latest_generated_resume_text and set resumes.latest_generated_format; format_converter may also update latest_generated_format and store converted artifact locations in processing_jobs.output_json.
- anonymize_resume must write resumes.anonymized_resume_json and must not remove the original parsed_resume_json.
- grammar_check, keyword_optimizer, ats_friendliness_check, resume_score, skill_gap_analyzer, summarize_experience must store their results in processing_jobs.output_json and may optionally update resumes.latest_generated_resume_text only when they are applied via apply_ats_suggestions.
- import_linkedin must create or update a linkedin_profiles record, write linkedin_profiles.normalized_resume_json when successful, and create/refresh a resumes row with source_type='linkedin' whose parsed_resume_json is derived from the normalized profile.
- extract_linkedin_profile_api and extract_linkedin_profile must set linkedin_profiles.status through pending->processing->ready/failed and store raw_profile_json on success.
- subscribe_to_resource must create an active resource_subscriptions row; unsubscribe_from_resource must transition the matching subscription to deleted (soft-delete) rather than physically removing it.
- list_resource_subscriptions must return only subscriptions where status in ('active','paused') for the caller workspace.
- trigger_test_notifications must create a processing_jobs row and attempt delivery to endpoint_url for matching subscriptions; delivery results must be recorded in processing_jobs.output_json and update resource_subscriptions.last_notified_at on success.
- Workspace quotas: creating a new processing_jobs row with status queued must be rejected if the workspace is suspended/deleted, if monthly_job_limit is exceeded, or if projected token usage would exceed monthly_token_limit.
- FK integrity for polymorphic resource_subscriptions.resource_id must be enforced by application logic: when resource_type='resume' resource_id must exist in resumes; when 'processing_job' must exist in processing_jobs; when 'linkedin_profile' must exist in linkedin_profiles.