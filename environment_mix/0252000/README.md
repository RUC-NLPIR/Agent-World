# Slack — local MCP environment

This backend stores a mirrored subset of a Slack workspace needed to support listing channels, reading message history and threads, posting messages, adding reactions, and fetching users and profiles. The main workflows are (1) syncing workspace/channel/user metadata, (2) writing messages and reactions with delivery status, and (3) reading channel history and thread replies keyed by Slack timestamps.

Repository: https://github.com/smithery-ai/mcp-servers
Homepage: https://smithery.ai/server/@smithery-ai/slack

## Datastore

- `workspaces.json` — Slack workspaces (teams) connected to this service, including auth/install metadata used to call Slack APIs. (18 rows; fields: ['id', 'slack_team_id', 'team_name', 'enterprise_id', 'bot_user_id', 'oauth_access_token_ciphertext', 'scopes', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'suspended']
  - constraint: unique(slack_team_id)
  - constraint: status in ('active','revoked','suspended')
  - constraint: length(slack_team_id) >= 2
- `channels.json` — Channels within a workspace used for listing and reading/writing messages. (18 rows; fields: ['id', 'workspace_id', 'slack_channel_id', 'name', 'type', 'is_archived', 'is_member', 'topic', 'purpose', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'inaccessible', 'deleted']
  - constraint: unique(workspace_id, slack_channel_id)
  - constraint: type in ('public_channel','private_channel','im','mpim')
  - constraint: is_archived = true implies status in ('archived','deleted')
- `users.json` — Users in a workspace, including basic and detailed profile fields used by list/get profile tools. (19 rows; fields: ['id', 'workspace_id', 'slack_user_id', 'username', 'display_name', 'real_name', 'email', 'title', 'phone', 'timezone', 'profile_image_72', 'is_bot', 'is_deleted', 'status', 'last_profile_fetch_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deactivated', 'deleted']
  - constraint: unique(workspace_id, slack_user_id)
  - constraint: is_deleted = true implies status = 'deleted'
- `messages.json` — Messages posted in channels, including thread structure and delivery metadata to support post/history/thread tools. (19 rows; fields: ['id', 'workspace_id', 'channel_id', 'slack_ts', 'slack_client_msg_id', 'user_id', 'text', 'thread_root_message_id', 'thread_root_slack_ts', 'message_type', 'status', 'failure_reason', 'sent_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'sent', 'failed', 'deleted']
  - constraint: unique(workspace_id, channel_id, slack_ts) where slack_ts is not null
  - constraint: unique(workspace_id, slack_client_msg_id) where slack_client_msg_id is not null
  - constraint: thread_root_message_id is null OR thread_root_message_id != id
  - constraint: thread_root_message_id is not null implies thread_root_slack_ts is not null
- `reactions.json` — Emoji reactions to messages, used by slack_add_reaction and for read-back/consistency. (19 rows; fields: ['id', 'workspace_id', 'message_id', 'channel_id', 'emoji', 'reacting_user_id', 'status', 'failure_reason', 'applied_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'applied', 'failed', 'removed']
  - constraint: unique(message_id, emoji, reacting_user_id) where reacting_user_id is not null and status != 'removed'
  - constraint: length(emoji) >= 1
  - constraint: channel_id must match messages.channel_id (enforced in application or via deferred constraint)

## Business rules enforced by the tools

- slack_list_channels returns channels where channels.workspace_id = current workspace and channels.status != 'deleted'; ordering defaults to (type asc, name asc, slack_channel_id asc).
- slack_get_users returns users where users.workspace_id = current workspace; users marked is_deleted=true must return status='deleted'.
- slack_get_user_profile requires a valid slack_user_id or internal user id resolvable within the current workspace; on fetch it refreshes users.* profile fields and sets last_profile_fetch_at = now().
- slack_get_channel_history requires a channel resolvable to channels.slack_channel_id within the current workspace; it returns messages for that channel ordered by slack_ts desc (or created_at desc for queued items), excluding messages.status='deleted'.
- slack_get_thread_replies requires a parent message resolvable by (channel, slack_ts) or internal message id; it returns the root message plus replies where thread_root_message_id=root.id OR thread_root_slack_ts=root.slack_ts, ordered by slack_ts asc.
- slack_post_message must create a messages row with status='queued' then attempt Slack send; on success set status='sent', slack_ts, sent_at; on failure set status='failed' and failure_reason. If posting a thread reply, it must set thread_root_message_id (or thread_root_slack_ts) and enforce that the root message belongs to the same channel/workspace.
- slack_add_reaction must create a reactions row with status='queued' then attempt Slack reactions.add; on success set status='applied' and applied_at; on failure set status='failed' and failure_reason. It must reject emojis not matching ^[a-z0-9_+\-]+$ (Slack-style names).
- FK integrity: messages.workspace_id must equal channels.workspace_id for its channel_id; reactions.workspace_id must equal messages.workspace_id and channels.workspace_id for its channel_id (enforced in application layer if not supported as a composite FK).
- Workspace status enforcement: if workspaces.status != 'active', all mutating operations (post message, add reaction) must be rejected and no queued rows may be created.
- Idempotency: if Slack returns slack_client_msg_id (or caller provides one), slack_post_message must not create a second sent message with the same (workspace_id, slack_client_msg_id); instead it should return the existing message.
- Data retention: history/thread read tools may return messages only up to a configured max (e.g., 1000) per request; the backend may prune old messages but must never violate uniqueness constraints on remaining rows.