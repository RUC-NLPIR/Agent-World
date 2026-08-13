# Slack User MCP Server — local MCP environment

This backend stores a cached representation of a Slack workspace: users, channels, messages, thread relationships, and reactions, along with an installation record that holds the Slack OAuth tokens used to call Slack APIs. The main workflows are (1) periodically syncing users/channels and optionally message history, and (2) creating new message/reply/reaction events while persisting Slack-returned IDs/timestamps for later reads.

Repository: https://github.com/lars-hagen/slack-user-mcp
Homepage: https://smithery.ai/server/@lars-hagen/slack-user-mcp

## Datastore

- `slack_installations.json` — Represents an installed Slack workspace (team) with OAuth credentials and connection lifecycle. Used by all tools to determine which workspace to act on and which token to use. (11 rows; fields: ['id', 'team_id', 'team_name', 'enterprise_id', 'bot_user_id', 'scopes', 'access_token_ciphertext', 'refresh_token_ciphertext', 'token_expires_at', 'status', 'last_api_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'disabled']
  - constraint: unique(team_id)
  - constraint: status in ('active','revoked','disabled')
  - constraint: token_expires_at is null or token_expires_at > created_at
- `slack_users.json` — Slack users in an installation, including basic and detailed profile information. Serves slack_get_users and slack_get_user_profile. (18 rows; fields: ['id', 'installation_id', 'slack_user_id', 'real_name', 'display_name', 'email', 'title', 'phone', 'image_48', 'timezone', 'is_bot', 'is_deleted', 'profile_raw', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deactivated']
  - constraint: foreign key (installation_id) references slack_installations(id) on delete cascade
  - constraint: unique(installation_id, slack_user_id)
  - constraint: email is null or email like '%@%'
  - constraint: status in ('active','deactivated')
- `slack_channels.json` — Slack channels in an installation, including metadata needed to list channels and validate posting targets. Serves slack_list_channels and channel selection for message/history tools. (18 rows; fields: ['id', 'installation_id', 'slack_channel_id', 'name', 'is_private', 'is_archived', 'topic', 'purpose', 'member_count', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: foreign key (installation_id) references slack_installations(id) on delete cascade
  - constraint: unique(installation_id, slack_channel_id)
  - constraint: member_count is null or member_count >= 0
  - constraint: status in ('active','archived')
- `slack_messages.json` — Messages posted or fetched from Slack, including thread root/replies and enough metadata to serve channel history and thread replies. Mutated by slack_post_message and slack_reply_to_thread; read by slack_get_channel_history and slack_get_thread_replies. (19 rows; fields: ['id', 'installation_id', 'channel_id', 'slack_channel_id', 'slack_ts', 'thread_ts', 'parent_message_id', 'author_user_id', 'slack_author_user_id', 'text', 'blocks', 'attachments', 'message_type', 'posted_via', 'status', 'slack_permalink', 'slack_created_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'deleted']
  - constraint: foreign key (installation_id) references slack_installations(id) on delete cascade
  - constraint: foreign key (channel_id) references slack_channels(id) on delete cascade
  - constraint: foreign key (author_user_id) references slack_users(id) on delete set null
  - constraint: foreign key (parent_message_id) references slack_messages(id) on delete set null
- `slack_reactions.json` — Emoji reactions on messages. Mutated by slack_add_reaction; optionally hydrated during history sync. Supports reaction readback if needed and enforces uniqueness per user/message/emoji. (19 rows; fields: ['id', 'installation_id', 'message_id', 'slack_channel_id', 'slack_message_ts', 'emoji_name', 'reacting_user_id', 'slack_reacting_user_id', 'posted_via', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign key (installation_id) references slack_installations(id) on delete cascade
  - constraint: foreign key (message_id) references slack_messages(id) on delete cascade
  - constraint: foreign key (reacting_user_id) references slack_users(id) on delete set null
  - constraint: emoji_name != ''

## Business rules enforced by the tools

- All tools operate within exactly one slack_installations row in status='active'; if none exists, tool calls must fail with a configuration error.
- slack_list_channels returns slack_channels where installation_id matches and status in ('active','archived'); ordering defaults to name asc with nulls last.
- slack_get_users returns slack_users for the installation; users with is_deleted=true must have status='deactivated'.
- slack_get_user_profile must resolve a user by (installation_id, slack_user_id) or (installation_id, id); if not found, it must fetch from Slack and upsert slack_users.profile_raw and normalized fields, setting last_synced_at=now().
- slack_post_message must only allow posting to a channel that exists in slack_channels for the installation and is_archived=false; on success it must upsert a slack_messages row with unique(installation_id, slack_channel_id, slack_ts) and posted_via='api'.
- slack_reply_to_thread must create a slack_messages row with message_type='reply' and thread_ts set; if parent/root message exists it should set parent_message_id accordingly; if not, it must still store the reply keyed by (slack_channel_id, slack_ts) and leave parent_message_id null.
- slack_get_channel_history reads slack_messages filtered by channel_id (or slack_channel_id) and excludes status='deleted' unless explicitly requested by implementation; it may backfill by calling Slack and upserting with posted_via='sync'.
- slack_get_thread_replies returns slack_messages where (channel_id matches) and thread_ts equals the requested root ts; thread root itself may be included if Slack returns it, but replies must have message_type in ('reply','message') and status='visible'.
- slack_add_reaction must target an existing slack_messages row or be able to resolve it by (installation_id, slack_channel_id, slack_ts); on success it must upsert slack_reactions with status='active', posted_via='api', enforcing unique(installation_id, message_id, emoji_name, slack_reacting_user_id).
- Token use must enforce that slack_installations.scopes include the required Slack scopes for each tool; otherwise the call must fail before attempting Slack API.
- FK integrity must be enforced: slack_channels.installation_id, slack_users.installation_id, slack_messages.installation_id and slack_reactions.installation_id must all reference the same slack_installations.id for any related rows (no cross-workspace joins).