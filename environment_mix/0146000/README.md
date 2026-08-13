# Logseq Tools — local MCP environment

This backend stores Logseq graph content (pages and blocks) plus derived link relationships and analysis/query runs over that content. Core workflows include creating pages and journal entries/blocks/content, retrieving pages/blocks, searching pages, computing backlinks, and running higher-level analytics (graph analysis, knowledge gaps, pattern analysis, smart queries, and connection suggestions) with persisted run history.

Repository: https://github.com/joelhooks/logseq-mcp-tools
Homepage: https://smithery.ai/server/@joelhooks/logseq-mcp-tools

## Datastore

- `graphs.json` — A Logseq graph (a workspace/knowledge base) that contains pages and blocks. Most tools operate within a single active graph. (12 rows; fields: ['id', 'slug', 'display_name', 'description', 'timezone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'read_only', 'archived']
  - constraint: unique(slug)
  - constraint: timezone must be a valid IANA timezone string
  - constraint: status in ('active','read_only','archived')
- `pages.json` — Logseq pages, including journal pages. Supports retrieval, creation, search, backlinks, and graph-level analysis. (33 rows; fields: ['id', 'graph_id', 'title', 'title_norm', 'is_journal', 'journal_date', 'properties', 'content_plaintext', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'archived']
  - constraint: fk(graph_id) references graphs(id)
  - constraint: unique(graph_id, title_norm) where status != 'deleted'
  - constraint: is_journal = true implies journal_date is not null
  - constraint: is_journal = false implies journal_date is null
- `blocks.json` — Logseq blocks (hierarchical) that live on pages. Supports getBlock and adding journal/note content via appends/inserts. (31 rows; fields: ['id', 'graph_id', 'page_id', 'parent_block_id', 'order_index', 'content_markdown', 'content_plaintext', 'properties', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(graph_id) references graphs(id)
  - constraint: fk(page_id) references pages(id)
  - constraint: parent_block_id is null OR fk(parent_block_id) references blocks(id) AND blocks.page_id = this.page_id
  - constraint: order_index >= 0
- `page_links.json` — Directed links between pages extracted from blocks (including [[wikilinks]] and #tags treated as page references). Powers backlinks and graph analysis. (36 rows; fields: ['id', 'graph_id', 'source_page_id', 'source_block_id', 'target_page_id', 'link_type', 'anchor_text', 'created_at', 'updated_at'])
  - constraint: fk(graph_id) references graphs(id)
  - constraint: fk(source_page_id) references pages(id)
  - constraint: fk(target_page_id) references pages(id)
  - constraint: fk(source_block_id) references blocks(id)
- `analysis_runs.json` — Persisted executions of higher-level tools (graph analysis, journal summaries/patterns, knowledge gap detection, smart queries, connection suggestions). Stores inputs/outputs for reproducibility and caching. (36 rows; fields: ['id', 'graph_id', 'tool_name', 'status', 'input', 'result', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(graph_id) references graphs(id)
  - constraint: tool_name in ('getJournalSummary','analyzeGraph','findKnowledgeGaps','analyzeJournalPatterns','smartQuery','suggestConnections')
  - constraint: status in ('queued','running','succeeded','failed','cancelled')
  - constraint: finished_at is null unless status in ('succeeded','failed','cancelled')

## Business rules enforced by the tools

- All tools operate against exactly one active graph; if multiple graphs exist, the server selects the single graph with status='active' and errors if none or more than one are active unless an internal default_graph_id is configured.
- getAllPages returns pages where pages.status='active' for the active graph, ordered by updated_at desc (or title asc) and may include is_journal/journal_date and basic properties.
- getPage resolves a page by exact title match on pages.title_norm within the active graph; if multiple historical rows exist, only status='active' is eligible.
- createPage creates a pages row with status='active' and title/title_norm unique within the graph; if a page with same title_norm exists and status!='deleted', the call must be idempotent (return existing page) or fail with a uniqueness error consistently.
- addJournalEntry ensures a journal page exists for 'today' in graph timezone; if absent it creates pages(is_journal=true, journal_date=today). It then appends a top-level block (parent_block_id null) to that journal page with increasing order_index.
- addJournalBlock inserts a new block under a provided parent (or top-level if none) on today's journal page; order_index must not collide with existing active siblings.
- addJournalContent and addNoteContent append or insert one or more blocks; they must update pages.content_plaintext and pages.updated_at, and create/update page_links derived from the new/changed blocks.
- getBlock returns a single block by id and must verify block.graph_id matches the active graph and block.status='active'.
- searchPages performs a text search over pages.title and pages.content_plaintext within the active graph, excluding pages.status!='active'.
- getBacklinks returns pages that link to a target page via page_links where target_page_id matches and both source_page and target_page are status='active'; results include counts grouped by source_page_id and optionally source blocks.
- analyzeGraph reads pages, blocks, and page_links to compute metrics (e.g., page count, link density, central pages) and persists an analysis_runs row with tool_name='analyzeGraph'.
- findKnowledgeGaps identifies pages with low inbound links or orphaned clusters using page_links; it must only consider pages.status='active' and store outputs in analysis_runs.result.
- analyzeJournalPatterns aggregates blocks from journal pages by journal_date (e.g., frequent topics/tags, streaks) using pages.is_journal and page_links(link_type='tag'); it persists an analysis_runs row.
- smartQuery executes a saved or ad-hoc query over pages/blocks (keywords, tags, backlinks); the full query spec is stored in analysis_runs.input and results in analysis_runs.result for caching.
- suggestConnections proposes new links between pages based on co-occurrence and shared neighbors in page_links; suggested edges are not written to page_links unless a separate confirm action exists (not in tool surface), so suggestions remain in analysis_runs.result only.
- Whenever a block's content_markdown changes (including new blocks), the system must re-extract outgoing page references from that block and upsert corresponding page_links, and delete stale edges for that block to maintain uniqueness(graph_id, source_block_id, target_page_id, link_type).