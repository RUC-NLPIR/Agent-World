# Dictionary MCP Server — local MCP environment

This backend powers a dictionary lookup MCP service that returns definitions for requested words. It stores a normalized lexical inventory (words/lemmas, senses/definitions, and example usages) plus request logs for auditing, caching, and operational monitoring of the get_definitions tool.

Repository: https://github.com/emro624/dictionary-mcp-main
Homepage: https://smithery.ai/server/@emro624/dictionary-mcp-main

## Datastore

- `lexicon_entries.json` — Canonical dictionary entries for a lemma/headword (optionally including language/normalized forms). Used as the primary lookup target for get_definitions(word). (18 rows; fields: ['id', 'headword', 'normalized_headword', 'language', 'pronunciation_ipa', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: unique(normalized_headword, language, source) where status != 'deleted'
  - constraint: headword length between 1 and 128
  - constraint: normalized_headword length between 1 and 128
- `entry_senses.json` — Definitions/senses for a lexicon entry (what get_definitions returns). Each sense is ordered for stable presentation. (18 rows; fields: ['id', 'entry_id', 'part_of_speech', 'definition', 'definition_plain', 'sense_order', 'labels', 'source_ref', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: foreign key(entry_id) references lexicon_entries(id) on delete restrict
  - constraint: unique(entry_id, sense_order) where status != 'deleted'
  - constraint: sense_order >= 1
  - constraint: definition length between 1 and 4000
- `sense_examples.json` — Example usages tied to a specific sense/definition to enrich responses and support future expansions. (18 rows; fields: ['id', 'sense_id', 'example_text', 'example_order', 'source_ref', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(sense_id) references entry_senses(id) on delete restrict
  - constraint: unique(sense_id, example_order) where status != 'deleted'
  - constraint: example_order >= 1
  - constraint: example_text length between 1 and 2000
- `definition_requests.json` — Operational/audit log of get_definitions calls for rate limiting, debugging, and cache tuning. Not required to serve lookups but typical for a production API. (18 rows; fields: ['id', 'word_raw', 'word_normalized', 'language', 'matched_entry_id', 'result_count', 'cache_status', 'latency_ms', 'status', 'error_message', 'request_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'not_found', 'failed', 'rate_limited']
  - constraint: result_count >= 0
  - constraint: latency_ms >= 0
  - constraint: word_raw length between 1 and 128
  - constraint: word_normalized length between 1 and 128

## Business rules enforced by the tools

- Tool get_definitions(word) must normalize the input into definition_requests.word_normalized and query lexicon_entries.normalized_headword for an exact match (language='en', status='active').
- If multiple lexicon_entries match the same normalized_headword across sources, the service must apply a deterministic preference rule (e.g., source priority) and log matched_entry_id accordingly.
- Returned definitions must come from entry_senses where entry_id=matched_entry_id and status='active', ordered by sense_order ascending.
- If the entry is found but has zero active senses, the response is treated as not_found (status='not_found') and result_count=0.
- Examples, if returned by the implementation, must come from sense_examples where sense_id belongs to returned senses and status='active', ordered by example_order ascending.
- All foreign keys must be valid at write time: entry_senses.entry_id must exist in lexicon_entries; sense_examples.sense_id must exist in entry_senses; definition_requests.matched_entry_id must exist when non-null.
- Deletion is logical via status transitions; once an entity is in status='deleted', it must never transition back to an active state.
- Uniqueness constraints must be enforced for (normalized_headword, language, source) among non-deleted entries and for (entry_id, sense_order) and (sense_id, example_order) among non-deleted children.
- Operational logging must record one definition_requests row per tool invocation, with cache_status in {hit, miss, bypass} and latency_ms >= 0.