# Pokémcp — local MCP environment

Pokémcp serves randomized Pokémon lookups (global, by region, by type) and answers natural-language Pokémon questions. The backend stores a local Pokémon reference catalog (species, regions, types), logs tool invocations for observability/quotas, and persists NL query sessions with the resolved intent and selected Pokémon results.

Repository: https://github.com/NaveenBandarage/poke-mcp
Homepage: https://smithery.ai/server/@NaveenBandarage/poke-mcp

## Datastore

- `pokemon.json` — Canonical Pokémon species records used for random selection and query answering (local cache of Pokédex-like data). (18 rows; fields: ['pokemon_id', 'national_dex_number', 'name', 'name_normalized', 'is_legendary', 'is_mythical', 'default_sprite_url', 'primary_region_id', 'status', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deprecated']
  - constraint: unique(national_dex_number)
  - constraint: unique(name_normalized)
  - constraint: national_dex_number >= 1
  - constraint: name <> ''
- `regions.json` — Pokémon regions (e.g., kanto, johto) used to filter random selections and support NL query intent resolution. (18 rows; fields: ['region_id', 'slug', 'display_name', 'dex_start', 'dex_end', 'generation', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(slug)
  - constraint: dex_start >= 1
  - constraint: dex_end >= dex_start
  - constraint: generation >= 1
- `types.json` — Pokémon elemental types (e.g., fire, water) used to filter random selections and support NL query intent resolution. (18 rows; fields: ['type_id', 'slug', 'display_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(slug)
- `pokemon_types.json` — Join table mapping Pokémon to one or more types; enables random selection by type and query reasoning. (18 rows; fields: ['pokemon_type_id', 'pokemon_id', 'type_id', 'slot', 'created_at', 'updated_at'])
  - constraint: unique(pokemon_id, type_id)
  - constraint: unique(pokemon_id, slot)
  - constraint: slot in (1,2)
- `tool_requests.json` — Audit log of tool invocations (random selection and NL query). Supports debugging, rate limiting, and reproducibility of random selections. (18 rows; fields: ['tool_request_id', 'tool_name', 'input_region', 'input_type', 'input_query', 'resolved_region_id', 'resolved_type_id', 'selected_pokemon_id', 'random_seed', 'status', 'error_message', 'duration_ms', 'client_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed']
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: tool_name in ('random-pokemon','random-pokemon-from-region','random-pokemon-by-type','pokemon-query')
  - constraint: ((tool_name = 'random-pokemon') implies (input_region is null and input_type is null and input_query is null))
  - constraint: ((tool_name = 'random-pokemon-from-region') implies (input_region is not null))

## Business rules enforced by the tools

- random-pokemon must select exactly one pokemon where pokemon.status='active'.
- random-pokemon-from-region must resolve the provided region (case-insensitive) to regions.slug and require regions.status='active'; selection must be one pokemon where pokemon.status='active' and pokemon.national_dex_number between regions.dex_start and regions.dex_end (inclusive).
- random-pokemon-by-type must resolve the provided type (case-insensitive) to types.slug and require types.status='active'; selection must be one pokemon where pokemon.status='active' joined through pokemon_types to the resolved type.
- pokemon-query must create a tool_requests row with tool_name='pokemon-query' and persist the raw input_query; the implementation may populate resolved_region_id and/or resolved_type_id when intent extraction succeeds.
- If a tool call returns a Pokémon, tool_requests.selected_pokemon_id must reference an active pokemon record; if the call fails, tool_requests.status='failed' and error_message must be non-null.
- Region and type resolution must be strict (no free-form persistence): tool_requests.resolved_region_id and resolved_type_id must always reference existing rows; unresolved inputs remain only in input_region/input_type.
- pokemon_types.slot must be 1 or 2 and each pokemon can have at most one row per slot.
- Deleting regions/types/pokemon records is disallowed in production; instead set status='disabled'/'deprecated'. Foreign key references from tool_requests must remain valid.