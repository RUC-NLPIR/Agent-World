# Pylon Server — local MCP environment

This backend stores a multi-tenant customer support system (workspaces) with accounts/contacts, issues (tickets) and their message threads, plus support teams/users, knowledge bases/articles, tags, ticket forms, and outbound webhooks. Core workflows are: manage customer records, create/search/update issues and conversations, publish self-serve knowledge articles, organize work via teams/tags/forms, and notify external systems via webhooks.

Repository: https://github.com/marcinwyszynski/pylon-mcp
Homepage: https://smithery.ai/server/@marcinwyszynski/pylon-mcp

## Datastore

- `workspaces.json` — Top-level tenant container for all Pylon objects. Used by pylon_get_me to resolve the caller's workspace context and by all list/search endpoints to scope data. (12 rows; fields: ['id', 'slug', 'name', 'status', 'plan', 'default_timezone', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
  - constraint: default_timezone <> ''
- `users_teams.json` — Users (support agents) and teams within a workspace, including membership and roles. Serves pylon_get_users, pylon_search_users, pylon_get_teams, pylon_get_team, pylon_create_team and issue assignment fields. (33 rows; fields: ['user_id', 'workspace_id', 'email', 'full_name', 'user_role', 'availability_status', 'user_status', 'team_id', 'team_name', 'team_type', 'team_status', 'specialization', 'team_memberships', 'created_at', 'updated_at'])
  - lifecycle `user_status`: ['active', 'invited', 'disabled']
  - constraint: unique(workspace_id, email) WHERE team_type='user'
  - constraint: unique(workspace_id, team_name) WHERE team_type='team' AND team_status='active'
  - constraint: team_type='user' => team_name is null AND team_status is null
  - constraint: team_type='team' => email is null AND user_role is null AND availability_status is null AND user_status is null
- `customers.json` — Customer accounts (companies) and contacts (people). Serves pylon_get_accounts, pylon_get_account, pylon_get_contacts, pylon_create_contact, pylon_search_contacts and provides linkage for issues. (30 rows; fields: ['id', 'workspace_id', 'entity_type', 'status', 'account_id', 'company_name', 'subscription_level', 'billing_status', 'contact_name', 'contact_email', 'contact_phone', 'contact_history', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: entity_type='account' => company_name is not null AND account_id is null AND contact_email is null
  - constraint: entity_type='contact' => contact_email is not null AND contact_name is not null
  - constraint: unique(workspace_id, contact_email) WHERE entity_type='contact' AND status <> 'deleted'
  - constraint: unique(workspace_id, company_name) WHERE entity_type='account' AND status <> 'deleted'
- `issues_messages_tags_forms.json` — Issues/tickets and their conversation messages, plus tag catalog and ticket forms. Serves pylon_get_issues, pylon_create_issue, pylon_get_issue, pylon_update_issue, pylon_snooze_issue, pylon_get_issue_messages, pylon_create_issue_message, pylon_get_tags, pylon_create_tag, pylon_get_ticket_forms, pylon_create_ticket_form, and pylon_search_issues. (34 rows; fields: ['id', 'workspace_id', 'entity_type', 'status', 'issue_id', 'account_id', 'contact_id', 'title', 'description', 'priority', 'assignee_user_id', 'team_id', 'ticket_form_id', 'tag_ids', 'snoozed_until', 'message_direction', 'sender_type', 'sender_user_id', 'sender_contact_id', 'body', 'tag_name', 'tag_color', 'form_name', 'form_schema', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'in_progress', 'pending', 'snoozed', 'resolved', 'closed', 'deleted', 'active', 'archived']
  - constraint: entity_type='issue' => title is not null AND priority is not null
  - constraint: entity_type='issue' => status in ['open','in_progress','pending','snoozed','resolved','closed','deleted']
  - constraint: entity_type='message' => issue_id is not null AND body is not null
  - constraint: entity_type='message' => status = 'active'
- `knowledge_webhooks.json` — Knowledge bases and articles for self-service support content, plus outbound webhooks for event delivery. Serves pylon_get_knowledge_bases, pylon_get_knowledge_base_articles, pylon_create_knowledge_base_article, pylon_get_webhooks, pylon_create_webhook, pylon_delete_webhook. (32 rows; fields: ['id', 'workspace_id', 'entity_type', 'status', 'knowledge_base_id', 'kb_name', 'kb_description', 'article_title', 'article_body', 'article_slug', 'published_at', 'author_user_id', 'webhook_url', 'webhook_secret', 'event_types', 'last_delivery_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted', 'enabled', 'disabled']
  - constraint: entity_type='knowledge_base' => kb_name is not null AND status in ['active','archived','deleted']
  - constraint: entity_type='knowledge_base_article' => knowledge_base_id is not null AND article_title is not null AND article_body is not null AND status in ['active','archived','deleted']
  - constraint: entity_type='webhook' => webhook_url is not null AND event_types is not null AND status in ['enabled','disabled']
  - constraint: unique(workspace_id, kb_name) WHERE entity_type='knowledge_base' AND status <> 'deleted'

## Business rules enforced by the tools

- All read/list/search tools must scope results by the caller's workspace_id resolved via pylon_get_me context; cross-workspace access is forbidden.
- pylon_create_contact creates a customers row with entity_type='contact', status='active', and requires contact_email and contact_name; if an account linkage is provided by internal UI, account_id must reference an entity_type='account' row in the same workspace.
- pylon_get_accounts returns customers rows where entity_type='account' and status != 'deleted'; pylon_get_account returns the account plus associated contacts (customers.entity_type='contact' with account_id) and issues (issues_messages_tags_forms.entity_type='issue' with account_id).
- pylon_search_contacts searches over (contact_name, contact_email) and joined account company_name (via account_id) within the same workspace; results exclude status='deleted'.
- pylon_create_issue creates an issues_messages_tags_forms row with entity_type='issue', status='open', and must reference a valid contact_id (entity_type='contact') in the same workspace; account_id is inferred from the contact's account_id when not explicitly set.
- pylon_update_issue may change title/description/priority/assignee_user_id/team_id/tag_ids and status, but must follow the declared status transitions; if setting status='snoozed', snoozed_until must be provided and be in the future.
- pylon_snooze_issue sets issue status to 'snoozed' and sets snoozed_until; it must not snooze issues in status 'closed' or 'deleted'.
- pylon_get_issue_messages returns message rows where entity_type='message' and issue_id matches; ordering is by created_at ascending.
- pylon_create_issue_message creates a message row with entity_type='message', status='active', issue_id set, and sender fields consistent with sender_type; internal_note messages must have message_direction='internal_note'.
- pylon_get_tags returns tag rows where entity_type='tag' and status='active'; pylon_create_tag enforces unique(workspace_id, tag_name) among active tags.
- pylon_get_ticket_forms returns ticket_form rows where entity_type='ticket_form' and status='active'; pylon_create_ticket_form requires a valid JSON form_schema and unique active form_name in the workspace.
- pylon_get_knowledge_bases returns knowledge_base rows where entity_type='knowledge_base' and status in ['active','archived']; article counts are derived by counting knowledge_base_article rows per knowledge_base_id where status='active'.
- pylon_get_knowledge_base_articles returns knowledge_base_article rows for the given knowledge_base_id (same workspace) excluding status='deleted'.
- pylon_create_knowledge_base_article creates a knowledge_base_article row with status='active', sets author_user_id to the caller user, and enforces unique article_slug within a knowledge base.
- pylon_get_webhooks returns webhook rows (entity_type='webhook') with status in ['enabled','disabled'] for the workspace; secrets are never returned in plaintext.
- pylon_create_webhook enforces per-workspace plan limits: free<=1 webhook, pro<=5, business<=20, enterprise<=100; event_types must be from the allowed set.
- pylon_delete_webhook performs a soft delete by setting status='disabled' and then status='deleted' (or removes the row) depending on retention policy; after deletion it must not appear in pylon_get_webhooks.
- pylon_search_users searches over users_teams user rows (team_type='user') by full_name and email, limited to user_status='active' or 'invited'.
- pylon_get_team returns the team row (team_type='team') plus expanded members from team_memberships; membership user ids must reference active user rows in the same workspace.