# Mobile Automation Server — local MCP environment

This backend manages a pool of mobile devices (simulators and physical iOS/Android), assigns them to automation sessions, and records device interactions executed through the API tools. Primary workflows are: discover devices, reserve/select one for a session, then drive it (apps, navigation, input, screenshots, orientation) while auditing all actions and storing transient artifacts (screenshots, UI element snapshots).

Repository: https://github.com/mobile-next/mobile-mcp
Homepage: https://smithery.ai/server/@mobile-next/mobile-mcp

## Datastore

- `devices.json` — Inventory of all known mobile targets (simulators and physical devices) that can be listed and reserved for automation. (31 rows; fields: ['id', 'display_name', 'device_type', 'platform_version', 'hardware_model', 'udid', 'host_agent', 'screen_width_px', 'screen_height_px', 'current_orientation', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'reserved', 'busy', 'offline', 'disabled']
  - constraint: unique(display_name, device_type)
  - constraint: unique(udid) where udid is not null
  - constraint: screen_width_px is null or screen_width_px > 0
  - constraint: screen_height_px is null or screen_height_px > 0
- `sessions.json` — Automation sessions that reserve a device and act as the context for subsequent tool calls (launch app, tap, type, screenshot, etc.). (17 rows; fields: ['id', 'device_id', 'requested_device_name', 'requested_device_type', 'status', 'selected_at', 'ended_at', 'last_action_at', 'current_app_package', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'ended', 'expired', 'failed']
  - constraint: requested_device_type in ('simulator','ios','android')
  - constraint: selected_at <= coalesce(ended_at, selected_at)
  - constraint: device_id references devices(id) on delete restrict
  - constraint: At most one active session per device: unique(device_id) where status = 'active'
- `device_apps.json` — Installed applications discovered on devices. Used to power list apps and validate launch/terminate requests. (33 rows; fields: ['id', 'device_id', 'package_name', 'display_name', 'version_name', 'version_code', 'is_system_app', 'last_scanned_at', 'created_at', 'updated_at'])
  - constraint: unique(device_id, package_name)
  - constraint: package_name <> ''
  - constraint: device_id references devices(id) on delete cascade
- `session_actions.json` — Append-only audit log of every tool invocation performed within a session, including inputs, outputs metadata, and errors. Also stores the latest UI snapshot references and screenshot artifacts when applicable. (32 rows; fields: ['id', 'session_id', 'device_id', 'tool_name', 'status', 'input', 'error_code', 'error_message', 'result', 'screenshot_artifact_id', 'ui_snapshot_artifact_id', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: session_id references sessions(id) on delete cascade
  - constraint: device_id references devices(id) on delete restrict
  - constraint: duration_ms is null or (duration_ms >= 0 and duration_ms <= 300000)
  - constraint: error_message is null when status != 'failed'
- `artifacts.json` — Blob metadata for large outputs produced by device operations (screenshots and UI element snapshots). The binary payload lives in object storage; this table tracks location, mime type, and retention. (34 rows; fields: ['id', 'session_id', 'device_id', 'artifact_type', 'mime_type', 'byte_size', 'storage_uri', 'sha256', 'status', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'expired', 'deleted']
  - constraint: session_id references sessions(id) on delete cascade
  - constraint: device_id references devices(id) on delete restrict
  - constraint: byte_size >= 0
  - constraint: storage_uri <> ''

## Business rules enforced by the tools

- mobile_list_available_devices returns devices where status in ('available','reserved') AND (status='available' OR there is an active session reserving it for the caller context), excluding devices with status in ('offline','disabled').
- mobile_use_device must atomically: (1) find a devices row matching (display_name=device AND device_type=deviceType), (2) ensure device.status='available', (3) create a sessions row in status='active', (4) set devices.status='reserved'. If any step fails, no state is changed.
- At most one sessions row with status='active' may exist per device (enforced by partial unique constraint).
- All device-driving tools (list_apps, launch_app, terminate_app, get_screen_size, click, list_elements, press_button, open_url, swipe, type_keys, take_screenshot, set_orientation, get_orientation) require an active session; they must record a session_actions row.
- mobile_list_apps refreshes/updates device_apps for the session's device and returns the current set; it may upsert by (device_id, package_name).
- mobile_launch_app and mobile_terminate_app require packageName to exist in device_apps for that device OR be explicitly allowlisted by server config; on success sessions.current_app_package is set/cleared respectively.
- mobile_click_on_screen_at_coordinates enforces 0 <= x < devices.screen_width_px and 0 <= y < devices.screen_height_px when the device has known screen dimensions; otherwise it rejects the call or first resolves size via mobile_get_screen_size.
- swipe_on_screen accepts only direction in ('up','down') and records the direction in session_actions.input.
- mobile_type_keys requires submit boolean; when submit=true it must also emit a virtual ENTER key event (recorded in session_actions.result metadata).
- mobile_press_button validates button compatibility: BACK is allowed only when devices.device_type='android'; DPAD_* buttons are allowed only when device is Android TV-capable (tracked via devices.hardware_model/host config). Invalid combinations fail the action.
- mobile_set_orientation updates devices.current_orientation and returns the new state; only values in ('portrait','landscape') are accepted.
- mobile_get_orientation returns devices.current_orientation; if unknown it must query the device and then update devices.current_orientation.
- mobile_take_screenshot and mobile_list_elements_on_screen must not be cached by clients; server still stores artifacts with short retention (artifacts.expires_at set) and links them from session_actions.
- When a session ends/expires/fails (internal timeout/cleanup), devices.status must transition from 'reserved'/'busy' back to 'available' unless the device is offline/disabled.
- Artifacts larger than a configured limit (e.g., 10MB screenshots or 5MB UI snapshots) are rejected and the action is marked failed with an error_code like 'artifact_too_large'.