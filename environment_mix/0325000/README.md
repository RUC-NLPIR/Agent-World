# Interactive Feedback — local MCP environment

This backend stores interactive feedback requests tied to a local project directory and a one-line change summary. The main workflow is: create a feedback request, snapshot basic project metadata, generate one or more questions/prompts for the user, and record user responses to close out the request.

Repository: https://github.com/QuantumLeap-us/interactive-feedback-mcp
Homepage: https://smithery.ai/server/@QuantumLeap-us/interactive-feedback-mcp

## Datastore

- `projects.json` — Represents a locally-referenced project directory that can receive interactive feedback requests. Stores normalized directory identity and lightweight metadata for deduplication and audit. (31 rows; fields: ['id', 'directory_path', 'directory_path_canonical', 'display_name', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(directory_path_canonical)
  - constraint: directory_path <> ''
  - constraint: directory_path_canonical <> ''
- `feedback_requests.json` — A single interactive feedback session request for a given project directory and change summary. This is the primary entity created by the interactive_feedback tool call. (35 rows; fields: ['id', 'project_id', 'project_directory', 'summary', 'request_source', 'client_request_id', 'opened_at', 'closed_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'active', 'awaiting_user', 'completed', 'cancelled', 'errored']
  - constraint: project_directory <> ''
  - constraint: summary <> ''
  - constraint: length(summary) <= 280
  - constraint: foreign key(project_id) references projects(id) on delete restrict
- `project_snapshots.json` — Immutable snapshots of lightweight project state captured at the time of a feedback request (e.g., file list and optional repository metadata). Used to ground interactive questions and provide reproducibility. (35 rows; fields: ['id', 'feedback_request_id', 'directory_path_canonical', 'git_repo_root', 'git_head_ref', 'git_head_sha', 'file_count', 'files', 'created_at', 'updated_at'])
  - lifecycle `status`: ['captured', 'invalidated']
  - constraint: foreign key(feedback_request_id) references feedback_requests(id) on delete cascade
  - constraint: file_count >= 0
  - constraint: file_count = array_length(files)
  - constraint: unique(feedback_request_id)
- `feedback_prompts.json` — Prompts/questions generated for a feedback request. These are the units presented to the user during an interactive session. (31 rows; fields: ['id', 'feedback_request_id', 'sequence_no', 'prompt_type', 'title', 'body', 'choices', 'is_required', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'presented', 'answered', 'skipped']
  - constraint: foreign key(feedback_request_id) references feedback_requests(id) on delete cascade
  - constraint: sequence_no >= 1
  - constraint: unique(feedback_request_id, sequence_no)
  - constraint: body <> ''
- `feedback_responses.json` — User responses to feedback prompts. Stores the actual interactive input collected during the session. (31 rows; fields: ['id', 'feedback_request_id', 'prompt_id', 'response_type', 'response_text', 'selected_choices', 'response_boolean', 'responded_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'redacted']
  - constraint: foreign key(feedback_request_id) references feedback_requests(id) on delete cascade
  - constraint: foreign key(prompt_id) references feedback_prompts(id) on delete cascade
  - constraint: unique(prompt_id)
  - constraint: (response_type = 'text' and response_text is not null and response_text <> '') or (response_type <> 'text')

## Business rules enforced by the tools

- A call to tool interactive_feedback(project_directory, summary) must create (or find) a projects row by directory_path_canonical, then create a feedback_requests row with project_directory and summary stored verbatim.
- project_directory and summary are required and must be non-empty strings; summary length must be <= 280 characters.
- When a feedback_requests row is created, status starts at queued; it may only transition according to the declared lifecycle transitions.
- At most one project_snapshots row may exist per feedback_request (unique(feedback_request_id)); snapshots are captured while the request is queued or active.
- A feedback_prompt must belong to exactly one feedback_request; sequence_no must start at 1 and be unique within the request.
- A feedback_response must belong to exactly one prompt, and each prompt may have at most one response (unique(prompt_id)).
- If a prompt is marked is_required=true, the feedback_request cannot transition to completed unless that prompt has a recorded response (or the prompt status is answered).
- Cancelling or erroring a feedback_request must set closed_at; completing must set closed_at and ensure all required prompts are answered.
- Foreign key integrity must be enforced for all references; deleting a feedback_request must cascade delete its snapshot, prompts, and responses.