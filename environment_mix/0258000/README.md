# Audiense Insights — local MCP environment

This backend stores Audiense Insights intelligence reports, the audiences and segments they contain, and the derived insight artifacts (aggregations, content engagement, influencer comparisons, and AI-generated summaries). Primary workflows are: list reports, fetch report details/segments, fetch audience-level insights and content analytics, retrieve reference data (baselines, affinity categories), and generate/read a cached report summary.

Repository: https://github.com/AudienseCo/mcp-audiense-insights
Homepage: https://smithery.ai/server/@AudienseCo/mcp-audiense-insights

## Datastore

- `intelligence_reports.json` — Top-level Audiense Intelligence Reports. Used by get-reports and get-report-info; also anchors segments/audiences and report-summary generation. (18 rows; fields: ['id', 'external_report_id', 'name', 'segmentation_type', 'audience_size', 'country', 'status', 'access_links', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'syncing', 'ready', 'failed', 'archived']
  - constraint: unique(external_report_id)
  - constraint: audience_size is null OR audience_size >= 0
  - constraint: country is null OR length(country) = 2
- `report_segments.json` — Segments within a report; each segment is associated with an Audiense audience entity. Returned as part of get-report-info and used by report-summary. (18 rows; fields: ['id', 'report_id', 'external_segment_id', 'audience_id', 'name', 'description', 'size', 'rank', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'syncing', 'ready', 'failed', 'archived']
  - constraint: foreign key(report_id) references intelligence_reports(id) on delete cascade
  - constraint: foreign key(audience_id) references audiences(id) on delete restrict
  - constraint: unique(report_id, external_segment_id)
  - constraint: rank is null OR rank >= 0
- `audiences.json` — Audiences represent an identifiable group of social accounts/users as analyzed by Audiense. Used by get-audience-insights, get-audience-content, and compare-audience-influencers. (18 rows; fields: ['id', 'external_audience_id', 'source', 'platform', 'country', 'size', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'syncing', 'ready', 'failed', 'deleted']
  - constraint: unique(external_audience_id)
  - constraint: size is null OR size >= 0
  - constraint: country is null OR length(country) = 2
- `audience_artifacts.json` — Materialized/cached analytics outputs per audience: aggregated insights distributions, content engagement breakdowns, and influencer comparison results. Serves get-audience-insights, get-audience-content, compare-audience-influencers, and supports report-summary without recomputing. (19 rows; fields: ['id', 'audience_id', 'artifact_type', 'categories', 'baseline_id', 'time_range', 'payload', 'payload_schema_version', 'computed_at', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'computing', 'ready', 'failed', 'expired']
  - constraint: foreign key(audience_id) references audiences(id) on delete cascade
  - constraint: payload_schema_version >= 1
  - constraint: unique(audience_id, artifact_type, coalesce(baseline_id,''), coalesce(categories_fingerprint,''), coalesce(time_range_fingerprint,''))
  - constraint: artifact_type != 'influencer_comparison' OR categories is not null
- `reference_data.json` — Reference datasets needed by tools: available baselines and affinity categories. Serves get-baselines and get-categories and can be referenced by cached artifacts. (18 rows; fields: ['id', 'ref_type', 'key', 'name', 'country', 'metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(ref_type, key)
  - constraint: country is null OR length(country) = 2
  - constraint: ref_type = 'baseline' OR country is null
- `report_summaries.json` — Cached/generated comprehensive summaries for a report, including segment highlights, top insights, and influencers. Serves report-summary tool. (19 rows; fields: ['id', 'report_id', 'summary_format', 'prompt_profile', 'payload', 'generated_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'generating', 'ready', 'failed', 'stale']
  - constraint: foreign key(report_id) references intelligence_reports(id) on delete cascade
  - constraint: unique(report_id, summary_format, coalesce(prompt_profile,''))

## Business rules enforced by the tools

- get-reports returns intelligence_reports where status != 'archived' by default, ordered by updated_at desc; archived can be included only via an internal flag (not exposed in current tool schema).
- get-report-info must return a report plus its report_segments (ordered by rank asc, nulls last) and must include access_links when intelligence_reports.status = 'ready'.
- A report in status 'ready' must have at least 1 segment in report_segments with status in ('ready','syncing') unless segmentation_type = 'none'.
- get-audience-insights reads the newest audience_artifacts row where artifact_type='insights' and status='ready' for the audience; if none exists or expires_at < now, a new artifact row is created with status='queued' and the tool either blocks until ready (bounded) or returns a retriable state.
- get-audience-content reads the newest audience_artifacts row where artifact_type='content_engagement' and status='ready' for the audience; if expired/missing, enqueue recomputation via status='queued'.
- compare-audience-influencers must validate that every requested category exists in reference_data where ref_type='affinity_category' and status='active'; otherwise reject.
- compare-audience-influencers stores/reads results in audience_artifacts with artifact_type='influencer_comparison' and a deterministic categories fingerprint; recompute if expired.
- get-baselines returns reference_data where ref_type='baseline' and status in ('active','deprecated'); when a country filter is applied internally, only baselines matching that country are returned plus global baselines where country is null.
- get-categories returns reference_data where ref_type='affinity_category' and status='active', ordered by name asc.
- report-summary must only generate a summary when intelligence_reports.status='ready'; otherwise it returns an error or a 'not ready' state. When segments or any underlying artifacts update after a ready summary, the summary status becomes 'stale'.
- FK integrity is enforced: deleting an intelligence_report cascades to report_segments and report_summaries; deleting an audience cascades to audience_artifacts but is restricted if still referenced by a non-archived report_segment (must archive segment first).