# Academic Author Network — local MCP environment

This backend stores canonical author profiles, their affiliations, extracted research keywords, and co-authorship links derived from external sources such as Google Scholar. The main workflows are (1) resolving an input name/surname (+ optional institution/field) to a specific author profile and (2) returning that author’s co-author network and/or keyword areas, using cached snapshots with source provenance and refresh lifecycles.

Repository: https://github.com/alperenkocyigit/AuthorProfileMCP
Homepage: https://smithery.ai/server/@alperenkocyigit/authorprofilemcp

## Datastore

- `authors.json` — Canonical author identities resolved from external sources (e.g., Google Scholar) and local disambiguation. Used as the primary entity for retrieving coauthors and keywords. (18 rows; fields: ['id', 'given_name', 'family_name', 'normalized_full_name', 'primary_institution', 'primary_field', 'google_scholar_profile_id', 'status', 'merged_into_author_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'disabled']
  - constraint: required(given_name, family_name, normalized_full_name, status, created_at, updated_at)
  - constraint: unique(google_scholar_profile_id) WHERE google_scholar_profile_id IS NOT NULL
  - constraint: unique(normalized_full_name, primary_institution) WHERE primary_institution IS NOT NULL AND status IN ('active','disabled')
  - constraint: merged_into_author_id IS NULL OR status = 'merged'
- `author_affiliations.json` — Affiliation history for authors. Supports optional institution-based disambiguation and richer profiles. (17 rows; fields: ['id', 'author_id', 'institution_name', 'department', 'is_current', 'start_year', 'end_year', 'source', 'created_at', 'updated_at'])
  - lifecycle `source`: ['google_scholar', 'user_submitted', 'imported', 'inferred']
  - constraint: required(author_id, institution_name, is_current, source, created_at, updated_at)
  - constraint: fk(author_id) references authors.id on update cascade on delete cascade
  - constraint: unique(author_id, institution_name, start_year, end_year)
  - constraint: start_year IS NULL OR (start_year >= 1900 AND start_year <= 2100)
- `author_keywords.json` — Normalized research keywords/areas for an author, typically extracted from Google Scholar and cached with provenance. (18 rows; fields: ['id', 'author_id', 'keyword', 'normalized_keyword', 'weight', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: required(author_id, keyword, normalized_keyword, source, status, created_at, updated_at)
  - constraint: fk(author_id) references authors.id on update cascade on delete cascade
  - constraint: unique(author_id, normalized_keyword) WHERE status = 'active'
  - constraint: weight IS NULL OR (weight >= 0 AND weight <= 1)
- `coauthorships.json` — Undirected co-author edges between two author profiles, optionally scoped/filtered by inferred field and supported by provenance. Used to serve get_coauthors. (18 rows; fields: ['id', 'author_id', 'coauthor_id', 'collaboration_count', 'primary_field', 'source', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'disabled']
  - constraint: required(author_id, coauthor_id, collaboration_count, source, status, created_at, updated_at)
  - constraint: fk(author_id) references authors.id on update cascade on delete cascade
  - constraint: fk(coauthor_id) references authors.id on update cascade on delete cascade
  - constraint: author_id != coauthor_id
- `profile_fetch_jobs.json` — Cache and refresh jobs that resolve (name, surname, institution) inputs to an author profile and update keywords/coauthors from Google Scholar. Supports reliability and prevents repeated scraping for identical inputs. (20 rows; fields: ['id', 'query_given_name', 'query_family_name', 'query_institution', 'query_field', 'resolved_author_id', 'status', 'provider', 'cache_key', 'error_code', 'error_message', 'started_at', 'finished_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: required(query_given_name, query_family_name, status, provider, cache_key, expires_at, created_at, updated_at)
  - constraint: fk(resolved_author_id) references authors.id on update cascade on delete set null
  - constraint: unique(cache_key)
  - constraint: expires_at > created_at

## Business rules enforced by the tools

- Tool get_author_keywords(name, surname, institution=null) MUST resolve to exactly one active authors row, preferring (a) exact match on normalized_full_name and current affiliation matching institution (case/whitespace-insensitive), then (b) exact match on google_scholar_profile_id if previously known for that input, else (c) highest-confidence author from latest succeeded profile_fetch_jobs for that cache_key. If no single author can be resolved, the call MUST fail with a deterministic 'not_found' or 'ambiguous_author' error.
- Tool get_author_keywords MUST return only author_keywords where author_id = resolved author, status='active'; keywords are deduped by normalized_keyword.
- Tool get_coauthors(name, surname, institution=null, field=null) MUST resolve the author using the same resolution logic; if field is provided, results MUST be filtered to coauthorships where primary_field matches the provided field (case-insensitive) OR where the coauthor has an active keyword matching the field token (implementation-defined mapping), but the filter behavior must be stable and documented.
- Tool get_coauthors MUST return coauthors based on coauthorships with status in ('active','stale'); status='disabled' edges MUST NOT be returned.
- Coauthorship edges MUST be stored canonically (enforced by author_id < coauthor_id or equivalent edge_key) to prevent duplicate undirected edges; the service MUST map queries to the correct direction when reading.
- When an authors row is merged (status='merged'), all reads MUST transparently follow merged_into_author_id to the active canonical author before returning keywords or coauthors.
- Creating or updating author_keywords/coauthorships from a provider refresh MUST upsert by the declared uniqueness constraints and update updated_at/last_seen_at; missing previously-seen edges MAY be transitioned from active->stale after a successful refresh.
- profile_fetch_jobs for identical normalized inputs MUST be deduplicated by cache_key; if an unexpired succeeded job exists, tools SHOULD use it rather than triggering a new fetch.
- collaboration_count MUST be a positive integer and SHOULD be updated monotonically non-decreasing for the same (author_id, coauthor_id, source) unless a provider correction is detected; decreases require marking the edge stale and revalidation.