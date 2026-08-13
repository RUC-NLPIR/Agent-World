# DART Financial Data Server — local MCP environment

This backend stores Korean DART (전자공시) issuer metadata, disclosures and their source artifacts (e.g., XBRL files), plus parsed/normalized financial statement line items and extracted business-section texts. The main workflows are: resolve a company by name, find relevant disclosures in a date range, fetch/parse XBRL (or fall back to JSON API-derived statements), and return either detailed statement items or business information sections; the system also tracks query/audit history for tool calls.

Repository: https://github.com/2geonhyup/dart-mcp
Homepage: https://smithery.ai/server/@2geonhyup/dart-mcp

## Datastore

- `companies.json` — Public companies/issuers resolvable by user-provided company_name; used to map requests to DART corp_code and support name/alias lookup. (18 rows; fields: ['id', 'corp_code', 'company_name_ko', 'company_name_en', 'name_aliases', 'stock_code', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'merged']
  - constraint: unique(corp_code)
  - constraint: unique(stock_code) where stock_code is not null
  - constraint: company_name_ko != ''
  - constraint: corp_code matches '^[0-9]{8}$'
- `disclosures.json` — Disclosure filings fetched from DART for a company; anchors date-range searches and links to source artifacts (XBRL/attachments) and report codes/years. (18 rows; fields: ['id', 'company_id', 'rcept_no', 'report_name', 'disclosure_date', 'bsns_year', 'reprt_code', 'has_xbrl', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['indexed', 'fetching', 'ready', 'failed', 'archived']
  - constraint: unique(rcept_no)
  - constraint: foreign key(company_id) references companies(id)
  - constraint: bsns_year between 1900 and 2100 when bsns_year is not null
  - constraint: disclosure_date is not null
- `source_artifacts.json` — Raw source files or API snapshots used to answer queries (XBRL zip, extracted XBRL instance, JSON API response blobs). Supports fallback behavior when XBRL parsing fails. (18 rows; fields: ['id', 'disclosure_id', 'artifact_type', 'source_url', 'storage_key', 'content_sha256', 'fetched_at', 'parse_status', 'parse_error', 'created_at', 'updated_at'])
  - lifecycle `parse_status`: ['not_parsed', 'parsing', 'parsed', 'parse_failed']
  - constraint: foreign key(disclosure_id) references disclosures(id)
  - constraint: unique(disclosure_id, artifact_type)
  - constraint: content_sha256 matches '^[a-f0-9]{64}$' when content_sha256 is not null
- `financial_statement_items.json` — Normalized financial statement line items extracted from XBRL (primary) or JSON API fallback. Supports detailed statement queries by type (BS/IS/CF) and by disclosure/year/report/fs_div. (18 rows; fields: ['id', 'company_id', 'disclosure_id', 'source_artifact_id', 'bsns_year', 'reprt_code', 'fs_div', 'statement_type', 'account_name', 'account_code', 'amount', 'currency', 'period_end', 'unit', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['extracted', 'validated', 'superseded']
  - constraint: foreign key(company_id) references companies(id)
  - constraint: foreign key(disclosure_id) references disclosures(id)
  - constraint: foreign key(source_artifact_id) references source_artifacts(id)
  - constraint: bsns_year between 1900 and 2100
- `business_information_sections.json` — Extracted narrative business information sections from disclosures (사업보고서 등): overview, products/services, materials/facilities, sales/orders, risks/derivatives, contracts/R&D, 기타 참고사항. (18 rows; fields: ['id', 'company_id', 'disclosure_id', 'source_artifact_id', 'information_type', 'content_text', 'language', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['extracted', 'validated', 'failed']
  - constraint: foreign key(company_id) references companies(id)
  - constraint: foreign key(disclosure_id) references disclosures(id)
  - constraint: foreign key(source_artifact_id) references source_artifacts(id)
  - constraint: unique(disclosure_id, information_type)
- `tool_requests.json` — Audit/log of MCP tool invocations (including tools with empty JSON-schema) capturing resolved inputs, execution outcome, and response pointers for observability and rate limiting. (17 rows; fields: ['id', 'tool_name', 'input', 'resolved_company_id', 'start_date', 'end_date', 'bsns_year', 'reprt_code', 'fs_div', 'statement_type', 'information_type', 'status', 'http_cache_hit', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: start_date is null or start_date matches '^[0-9]{8}$'
  - constraint: end_date is null or end_date matches '^[0-9]{8}$'
  - constraint: bsns_year is null or bsns_year matches '^[0-9]{4}$'
  - constraint: end_date is null or start_date is null or start_date <= end_date

## Business rules enforced by the tools

- Company resolution: a tool call that includes company_name (even if not present in published JSON-schema) must resolve to exactly one companies row by exact match on company_name_ko or contained in name_aliases; otherwise tool_requests.status must be set to failed with error_message indicating ambiguous/not found.
- Date range searches (search_disclosure, search_detailed_financial_data, search_business_information) must filter disclosures by company_id and disclosure_date between start_date and end_date inclusive (interpreting YYYYMMDD at local midnight boundaries).
- search_disclosure must return disclosures for the resolved company in the requested date range; if no disclosures exist, it must succeed with an empty result rather than failing.
- For search_detailed_financial_data: if statement_type is provided in Korean labels, it must map to statement_type enum as follows: 재무상태표->BS, 손익계산서->IS, 현금흐름표->CF; if statement_type is null/None, results may include all three types.
- search_detailed_financial_data should prefer items whose source_artifact.artifact_type is xbrl_instance or xbrl_zip with parse_status=parsed; if none exist for the selected disclosure(s), it may fall back to items sourced from json_financial_api artifacts (see next rule).
- search_json_financial_data must create or reuse a source_artifacts row with artifact_type=json_financial_api for the most relevant disclosure (matching company_id, bsns_year, reprt_code when possible). It must write normalized rows into financial_statement_items with matching (company_id, bsns_year, reprt_code, fs_div, statement_type).
- Uniqueness: for a given (company_id, bsns_year, reprt_code, fs_div, statement_type, account_name, period_end, account_code), only one non-superseded financial_statement_items row may exist; new ingestions must mark older duplicates as superseded within the same transaction.
- search_business_information must return content from business_information_sections for disclosures in the date range; if multiple disclosures contain the same information_type, the tool must prefer the latest disclosure_date unless the caller explicitly requests otherwise (no such parameter exists, so default to latest).
- Artifact parsing: when a parser starts, source_artifacts.parse_status transitions to parsing; on success it must be parsed; on error it must be parse_failed with parse_error populated. Direct transition from not_parsed to parsed is forbidden.
- Audit: every tool call (including get_current_date and tools with empty published parameter schemas) must insert one tool_requests row and transition status through received->running->(succeeded|failed).
- Input validation: reprt_code must be one of 11011/11012/11013/11014; fs_div must be OFS/CFS; statement_type must be one of BS/IS/CF or the Korean labels for the detailed tool; invalid inputs must fail the request without mutating financial_statement_items.
- Data retention: disclosures in archived status and their artifacts must remain readable for search tools, but new parsing/extraction writes are disallowed unless the disclosure is transitioned back to fetching by an internal job (not exposed as a tool).