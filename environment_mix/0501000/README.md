# Intruder — local MCP environment

This backend stores an Intruder account's vulnerability scanning inventory: targets (assets) with tags, scans executed against those targets, discovered issues, and per-target occurrences (findings) including scanner output. The main workflows are managing targets/tags, initiating and cancelling scans, and triaging findings by listing issues/occurrences and applying snoozes at issue or occurrence scope; license usage is tracked per target with a 30-day tie window.

Repository: https://github.com/intruder-io/intruder-mcp
Homepage: https://smithery.ai/server/@intruder-io/intruder-mcp

## Datastore

- `accounts_users.json` — Tenancy and identity for Intruder accounts. Supports get_user and get_status, and provides the account_id parent FK for all other collections. (17 rows; fields: ['id', 'record_type', 'account_id', 'account_name', 'account_status', 'email', 'full_name', 'role', 'last_login_at', 'api_status_cached', 'api_status_checked_at', 'created_at', 'updated_at'])
  - lifecycle `account_status`: ['active', 'suspended', 'closed']
  - constraint: record_type IN ('account','user')
  - constraint: record_type='user' => account_id IS NOT NULL
  - constraint: record_type='account' => account_id IS NULL
  - constraint: unique(email) WHERE record_type='user'
- `targets_tags.json` — Asset inventory (targets) and tagging. Supports list_targets, create_targets, delete_target, list_tags, create_target_tag, delete_target_tag, and filters by target_addresses/tag_names used by issues and occurrences listing. (18 rows; fields: ['id', 'record_type', 'account_id', 'target_id', 'tag_id', 'address', 'target_status', 'target_deleted_at', 'tag_name', 'tag_color', 'last_seen_live_at', 'created_at', 'updated_at'])
  - lifecycle `target_status`: ['live', 'license_exceeded', 'unscanned', 'unresponsive', 'agent_uninstalled', 'deleted']
  - constraint: record_type IN ('target','tag','target_tag')
  - constraint: unique(account_id, address) WHERE record_type='target' AND target_status!='deleted'
  - constraint: address IS NOT NULL WHERE record_type='target'
  - constraint: target_status IS NOT NULL WHERE record_type='target'
- `scans.json` — Scan jobs initiated against sets of targets. Supports create_scan, list_scans, get_scan, and cancel_scan. Stores resolved target selection (by address and/or tag) and per-target membership for reporting. (17 rows; fields: ['id', 'record_type', 'account_id', 'scan_id', 'target_id', 'status', 'scan_type', 'requested_target_addresses', 'requested_tag_names', 'resolved_target_count', 'started_at', 'ended_at', 'cancel_reason', 'created_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['in_progress', 'analysing_results', 'completed', 'cancelled', 'cancelled_no_active_targets', 'cancelled_no_valid_targets']
  - constraint: record_type IN ('scan','scan_target')
  - constraint: record_type='scan' => status IS NOT NULL AND scan_type IS NOT NULL
  - constraint: record_type='scan_target' => scan_id IS NOT NULL AND target_id IS NOT NULL
  - constraint: unique(account_id, scan_id, target_id) WHERE record_type='scan_target'
- `issues_occurrences.json` — Vulnerability issues (deduped definitions) and their occurrences on targets, including scanner output and snooze state. Supports list_issues, list_occurrences, get_scanner_output, snooze_issue, snooze_occurrence, and filters by target_addresses/tag_names/snoozed/severity. (19 rows; fields: ['id', 'record_type', 'account_id', 'issue_id', 'occurrence_id', 'target_id', 'scan_id', 'severity', 'title', 'description', 'first_seen_at', 'last_seen_at', 'occurrence_status', 'evidence', 'scanner_output', 'snoozed', 'snooze_scope', 'snooze_reason', 'snooze_details', 'snooze_duration_seconds', 'snooze_duration_type', 'snooze_expires_at', 'snooze_status', 'created_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `snooze_status`: ['active', 'expired', 'revoked']
  - constraint: record_type IN ('issue','occurrence','snooze')
  - constraint: record_type='issue' => severity IS NOT NULL AND title IS NOT NULL
  - constraint: record_type='occurrence' => issue_id IS NOT NULL AND target_id IS NOT NULL AND occurrence_status IS NOT NULL
  - constraint: record_type='snooze' => issue_id IS NOT NULL AND snooze_scope IS NOT NULL AND snooze_reason IS NOT NULL AND snooze_status IS NOT NULL
- `licenses.json` — License entitlements and usage tracking, including the 30-day tie of a consumed license to the target that used it. Supports list_licenses and enables computing target_status=license_exceeded. (18 rows; fields: ['id', 'record_type', 'account_id', 'license_id', 'license_kind', 'status', 'limit_total', 'used_current', 'period_start_at', 'period_end_at', 'target_id', 'bound_from_at', 'bound_until_at', 'usage_status', 'created_at', 'updated_at'])
  - lifecycle `usage_status`: ['bound', 'released', 'expired']
  - constraint: record_type IN ('license','license_usage')
  - constraint: record_type='license' => license_kind IS NOT NULL AND status IS NOT NULL AND limit_total IS NOT NULL
  - constraint: limit_total >= 0
  - constraint: used_current >= 0

## Business rules enforced by the tools

- All read/list tools operate within the authenticated user's account_id; cross-account access is forbidden by FK scoping checks.
- get_user returns the current authenticated user row (record_type='user') and its parent account summary (record_type='account').
- get_status returns accounts_users.api_status_cached; if api_status_checked_at is older than a configured TTL (e.g. 60s), it must be refreshed and updated atomically.
- create_targets inserts target rows for each address; address must be normalized (lowercased hostname, trimmed) and must satisfy a target address validator (domain/IPv4/IPv6/CIDR per product rules). Duplicate addresses within an account are rejected unless the existing target is target_status='deleted'.
- delete_target performs a soft delete: set target_status='deleted' and target_deleted_at=now; it must also delete/disable target_tag joins for that target and expire any bound license_usage rows for the target.
- create_target_tag upserts a tag (record_type='tag') by (account_id, tag_name), enforcing max length 40, then creates a target_tag join; duplicates are idempotent.
- delete_target_tag deletes the target_tag join for the given (target_id, tag_name); if the tag becomes orphaned (no target_tag rows), it may remain for reuse (no hard delete required).
- list_tags supports filtering by target_address by joining target_tag->target and returning only tags applied to the matching target.
- create_scan requires at least one of target_addresses or tag_names to be non-empty; it resolves to distinct live/non-deleted targets. If none resolve, the scan is created with status='cancelled_no_valid_targets' (or 'cancelled_no_active_targets' if all resolved targets are non-active due to license/state rules) and ended_at is set.
- cancel_scan is only allowed when scan.status IN ('in_progress','analysing_results'); it transitions to 'cancelled' and sets ended_at and cancel_reason='user_request'.
- list_scans filters by scans.status and scans.scan_type (scan headers only). get_scan returns a scan header plus its scan_target membership.
- Issues are deduped at the account level (unique(account_id, issue_id) for record_type='issue'); occurrences are deduped per target (unique(account_id, issue_id, target_id) for record_type='occurrence').
- list_issues can filter by severity and snoozed; filtering by target_addresses/tag_names is implemented by joining occurrences to targets and target_tag/tag.
- list_occurrences requires issue_id and returns occurrence rows; it supports filters target_addresses/tag_names and snoozed similarly via joins. issue_id must refer to an issue row within the account.
- get_scanner_output requires (issue_id, occurrence_id) and returns issues_occurrences.scanner_output for that occurrence; it must verify the occurrence.issue_id matches the provided issue_id.
- snooze_issue creates (or replaces) an active snooze row with snooze_scope='issue' for the issue_id; it sets snooze_expires_at based on duration_seconds if provided; it must update materialized snoozed flags for the issue and all its occurrences to true while the snooze is active.
- snooze_occurrence creates (or replaces) an active snooze row with snooze_scope='occurrence' for the given occurrence_id under the issue_id; it sets expiry similarly and materializes snoozed=true for that occurrence.
- When a snooze expires (now > snooze_expires_at), a background job marks snooze_status='expired' and recomputes materialized snoozed flags (issue snooze overrides occurrence state).
- list_licenses returns license entitlements (record_type='license') including used_current computed as count of bound license_usage rows with bound_until_at > now and usage_status='bound', plus per-target bindings for transparency.
- A target may be marked target_status='license_exceeded' when creating scan membership if adding it would exceed active license.limit_total for the relevant license_kind; such targets are excluded from resolved scan_target rows and will trigger cancelled_no_active_targets if no eligible targets remain.