# PapersWithCode Client — local MCP environment

This backend mirrors key entities from PapersWithCode (research areas, tasks, authors, papers, conferences/proceedings) and their relationships, enabling search and detail retrieval. It also stores enrichments and cross-links (paper↔author, paper↔task, paper↔repo/dataset/method/result) to serve list endpoints and support reading/explaining a paper by URL via stored canonical URL mappings and cached parsed content.

Repository: https://github.com/hbg/mcp-paperswithcode
Homepage: https://smithery.ai/server/@hbg/mcp-paperswithcode

## Datastore

- `research_areas.json` — Top-level research areas in PapersWithCode; used for search and to enumerate tasks under an area. (18 rows; fields: ['id', 'slug', 'name', 'description', 'status', 'upstream_id', 'upstream_url', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: unique(slug)
  - constraint: unique(lower(name))
  - constraint: name <> ''
  - constraint: slug <> ''
- `tasks.json` — Tasks (and benchmarks) in PapersWithCode. Tasks can be associated with a research area and linked to papers. (18 rows; fields: ['id', 'area_id', 'slug', 'name', 'task_type', 'status', 'upstream_id', 'upstream_url', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: unique(slug)
  - constraint: unique(lower(name))
  - constraint: name <> ''
  - constraint: slug <> ''
- `authors.json` — Paper authors in PapersWithCode; supports searching by full name and listing papers for an author. (18 rows; fields: ['id', 'full_name', 'normalized_name', 'orcid', 'status', 'merged_into_author_id', 'upstream_id', 'upstream_url', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'deleted']
  - constraint: full_name <> ''
  - constraint: normalized_name = lower(full_name)
  - constraint: unique(orcid) where orcid is not null
  - constraint: merged_into_author_id is null or merged_into_author_id references authors(id)
- `venues.json` — Conferences and their proceedings (years/editions). Supports listing conferences, fetching a conference, listing proceedings, and getting a specific proceeding. (17 rows; fields: ['id', 'venue_type', 'conference_id', 'name', 'slug', 'year', 'location', 'start_date', 'end_date', 'status', 'upstream_id', 'upstream_url', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: venue_type in ('conference','proceeding')
  - constraint: conference_id is null or conference_id references venues(id)
  - constraint: venue_type='conference' implies conference_id is null
  - constraint: venue_type='proceeding' implies conference_id is not null
- `papers.json` — Papers plus their related entities (authors, tasks, repositories, datasets, methods, results) modeled as embedded child arrays to keep the collection count small while supporting all list/get endpoints. Also stores URL aliases and cached parsed content used by read_paper_from_url. (22 rows; fields: ['id', 'title', 'abstract', 'arxiv_id', 'doi', 'published_at', 'paper_url', 'url_aliases', 'conference_id', 'proceeding_id', 'status', 'authors', 'tasks', 'repositories', 'datasets', 'methods', 'results', 'cached_read', 'upstream_id', 'upstream_url', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'retracted', 'deleted']
  - constraint: title <> ''
  - constraint: unique(arxiv_id) where arxiv_id is not null
  - constraint: unique(doi) where doi is not null
  - constraint: conference_id is null or conference_id references venues(id)

## Business rules enforced by the tools

- Pagination parameters page and items_per_page must be treated as 1-indexed; if null, default to page=1 and items_per_page=20; items_per_page must be clamped to a safe maximum (e.g., 100).
- search_research_areas(name) performs case-insensitive substring match against research_areas.name and/or exact match against research_areas.slug; returns only status in ('active','deprecated') by default.
- get_research_area(area_id) must return 404/not-found when research_areas.id does not exist or status='deleted'.
- list_research_area_tasks(area_id) returns tasks where tasks.area_id=area_id and tasks.status!='deleted'.
- search_authors(full_name) uses authors.normalized_name for case-insensitive match and excludes authors.status='deleted'.
- get_paper_author(author_id) must follow merges: if authors.status='merged', the API returns the merged_into_author_id canonical author (or returns a 409 with canonical id depending on product choice), but must never return a deleted author.
- list_papers_by_author_id(author_id) returns papers where papers.authors contains author_id; if author is merged, treat merged_into_author_id as canonical for listing.
- list_papers_by_author_name(author_name) first resolves matching authors by normalized_name, then returns union of papers linked to those author ids.
- list_conferences(conference_name) filters venues where venue_type='conference' and (conference_name is null OR name ilike %conference_name%); excludes status='deleted'.
- get_conference(conference_id) must verify venues.venue_type='conference' and status!='deleted'.
- list_conference_proceedings(conference_id) returns venues where venue_type='proceeding' and conference_id matches and status!='deleted'.
- get_conference_proceeding(conference_id, proceeding_id) must verify proceeding belongs to conference and both are not deleted.
- list_conference_papers(conference_id, proceeding_id) returns papers where proceeding_id matches and conference_id matches and status!='deleted'.
- search_papers supports filtering by any combination of title/abstract/arxiv_id; arxiv_id match should be normalized (strip version) and exact; title/abstract are case-insensitive substring matches; excludes status='deleted'.
- get_paper(paper_id) returns 404 if not found or status='deleted'.
- list_paper_repositories/datasets/methods/results/tasks return the corresponding embedded arrays from papers for that paper_id; if paper not found or deleted, return 404.
- read_paper_from_url(paper_url) must canonicalize/normalize the URL and attempt resolution in this order: exact match on papers.paper_url, match in papers.url_aliases, match by detecting arxiv_id in the URL; if resolved, it may populate/update papers.cached_read with fetch_status and last_fetched_at.
- URL alias integrity: the same normalized URL must not appear in url_aliases of more than one paper; canonical paper_url must also be globally unique when non-null.
- FK integrity must be enforced on write paths (mirror/import jobs): embedded author/task ids in papers must exist (or be created in the same transaction/batch) before the paper is marked active.