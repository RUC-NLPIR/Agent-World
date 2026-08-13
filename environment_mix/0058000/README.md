# Dice Roller — local MCP environment

This backend stores dice roll requests and their computed outcomes for an API that accepts standard dice notation (e.g., 2d6+3). The primary workflow is creating a roll request, validating/parsing its notation, generating per-die results, and returning an aggregated total with an auditable history.

Repository: https://github.com/yamaton/mcp-dice
Homepage: https://smithery.ai/server/mcp-dice

## Datastore

- `api_keys.json` — API keys used to authenticate callers and apply per-key quotas/limits for the dice rolling API. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'rate_limit_per_minute', 'monthly_roll_cap', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: rate_limit_per_minute BETWEEN 1 AND 6000
  - constraint: monthly_roll_cap BETWEEN 0 AND 10000000
- `dice_rolls.json` — Top-level record of each dice roll request, including the original notation, parsed components, and computed totals. (18 rows; fields: ['id', 'api_key_id', 'notation', 'parsed_count', 'parsed_sides', 'parsed_modifier', 'sum_dice', 'total', 'status', 'rejection_reason', 'requested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['validated', 'rolled', 'rejected']
  - constraint: notation ~ '^\d+d\d+([+-]\d+)?$'
  - constraint: parsed_count BETWEEN 1 AND 1000
  - constraint: parsed_sides BETWEEN 2 AND 1000000
  - constraint: parsed_modifier BETWEEN -1000000 AND 1000000
- `dice_roll_results.json` — Child rows containing the outcome of each individual die rolled as part of a dice_roll. (18 rows; fields: ['id', 'dice_roll_id', 'die_index', 'result', 'created_at', 'updated_at'])
  - lifecycle ``: []
  - constraint: foreign key(dice_roll_id) references dice_rolls(id) on delete cascade
  - constraint: unique(dice_roll_id, die_index)
  - constraint: die_index >= 1
  - constraint: result >= 1
- `usage_counters.json` — Aggregated usage per API key per month used to enforce monthly caps without scanning all dice_rolls. (12 rows; fields: ['id', 'api_key_id', 'month', 'roll_count', 'rejected_count', 'created_at', 'updated_at'])
  - lifecycle ``: []
  - constraint: foreign key(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, month)
  - constraint: month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
  - constraint: roll_count >= 0

## Business rules enforced by the tools

- roll_dice(notation) must reject any notation that does not match ^\d+d\d+([+-]\d+)?$ and persist a dice_rolls row with status='rejected' and a non-null rejection_reason.
- For accepted requests, the service must parse notation into parsed_count, parsed_sides, parsed_modifier and persist status='validated' before producing results.
- The service must enforce bounds: 1 <= parsed_count <= 1000, 2 <= parsed_sides <= 1000000, and -1000000 <= parsed_modifier <= 1000000; requests outside these bounds must be rejected.
- When a roll is executed, exactly parsed_count dice_roll_results rows must be created with die_index 1..parsed_count and each result in the inclusive range [1, parsed_sides].
- After inserting dice_roll_results, the service must set dice_rolls.sum_dice to the sum of result values, set dice_rolls.total = sum_dice + parsed_modifier, and transition dice_rolls.status from 'validated' to 'rolled' atomically.
- dice_rolls.status transitions are constrained to validated -> rolled|rejected; rolled and rejected are terminal states.
- If the request is authenticated, api_keys.status must be 'active' or the request must be rejected and counted in usage_counters.rejected_count for that api_key_id and month.
- If authenticated, the service must increment usage_counters.roll_count for the api_key_id and month for each accepted roll (validated/rolled) and must prevent roll_count from exceeding api_keys.monthly_roll_cap when monthly_roll_cap > 0.
- Rate limiting uses api_keys.rate_limit_per_minute; requests beyond the limit must be rejected (or throttled) and should not create dice_roll_results rows.
- FK integrity: deleting a dice_roll must cascade-delete its dice_roll_results; deleting an api_key must cascade-delete its usage_counters and set dice_rolls.api_key_id to null (or delete associated dice_rolls depending on retention policy).