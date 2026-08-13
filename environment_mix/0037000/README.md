# Markdown Downloader — local MCP environment

This backend stores configuration for where markdown files are saved, a managed set of subdirectories under that root, and an audit trail of each webpage-to-markdown download performed via r.jina.ai. Core workflows are setting/getting the download root, creating/listing subdirectories, downloading a URL into a (sub)directory, and listing downloaded files (optionally filtered by subdirectory).

Repository: https://github.com/dazeb/markdown-downloader
Homepage: https://smithery.ai/server/@dazeb/markdown-downloader

## Datastore

- `download_settings.json` — Singleton-like settings for the service, primarily the root download directory and related policy flags. Supports get_download_directory and set_download_directory. (12 rows; fields: ['id', 'active', 'root_directory', 'root_directory_normalized', 'allow_relative_subdirectories', 'max_path_length', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'disabled']
  - constraint: unique(active) WHERE active = true (only one active settings record at a time)
  - constraint: root_directory must be an absolute path
  - constraint: max_path_length BETWEEN 64 AND 32767
  - constraint: root_directory_normalized is derived from root_directory and must be unique among active settings records
- `subdirectories.json` — Managed subdirectories under the active root download folder. Supports create_subdirectory and filtering/listing behaviors. (25 rows; fields: ['id', 'settings_id', 'name', 'name_normalized', 'relative_path', 'full_path', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: foreign key(settings_id) references download_settings(id) on delete restrict
  - constraint: unique(settings_id, name_normalized) WHERE status = 'active'
  - constraint: name length BETWEEN 1 AND 128
  - constraint: name must not be '.' or '..'
- `download_jobs.json` — A record of each requested markdown download from a URL, including chosen subdirectory and the final saved file reference. Supports download_markdown and auditing. (38 rows; fields: ['id', 'settings_id', 'subdirectory_id', 'requested_subdirectory', 'source_url', 'source_url_normalized', 'fetch_url', 'http_status', 'content_type', 'content_sha256', 'bytes_written', 'status', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'saving', 'succeeded', 'failed']
  - constraint: foreign key(settings_id) references download_settings(id) on delete restrict
  - constraint: foreign key(subdirectory_id) references subdirectories(id) on delete set null
  - constraint: http_status BETWEEN 100 AND 599 when not null
  - constraint: bytes_written >= 0 when not null
- `markdown_files.json` — Index of markdown files saved on disk, enabling list_downloaded_files and mapping saved outputs to their originating job/URL. (38 rows; fields: ['id', 'job_id', 'settings_id', 'subdirectory_id', 'relative_path', 'file_name', 'full_path', 'source_url', 'content_sha256', 'size_bytes', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted']
  - constraint: foreign key(job_id) references download_jobs(id) on delete restrict
  - constraint: foreign key(settings_id) references download_settings(id) on delete restrict
  - constraint: foreign key(subdirectory_id) references subdirectories(id) on delete set null
  - constraint: unique(settings_id, relative_path) WHERE status = 'present'

## Business rules enforced by the tools

- get_download_directory returns root_directory from the single active download_settings record; if none exists, the service must create one with status='active' and a platform-default root_directory.
- set_download_directory(directory) creates a new download_settings record with status='active' and sets any previously active record to status='superseded' in the same transaction; root_directory must be absolute and normalized into root_directory_normalized.
- create_subdirectory(name) must create a subdirectories row tied to the current active settings_id and must ensure the on-disk directory exists at full_path; attempting to create a duplicate (settings_id, name_normalized) with status='active' must be rejected.
- download_markdown(url, subdirectory?) must create a download_jobs row (status='queued'), transition through fetching/saving, and on success create exactly one markdown_files row linked by job_id; on failure it must set status='failed' and populate error_code.
- If download_markdown is called with subdirectory provided, the service must resolve it to an existing active subdirectories row for the active settings; if not found, it must fail with error_code='path_error' (unless the implementation explicitly auto-creates, in which case it must create_subdirectory first and then proceed).
- list_downloaded_files(subdirectory?) returns markdown_files with status='present' under the active settings_id; if subdirectory is provided, results must be filtered to files whose subdirectory_id matches the resolved subdirectory for that name under the active settings.
- A markdown_files row must only be created after its producing download_jobs row reaches status='succeeded', and markdown_files.size_bytes must equal download_jobs.bytes_written when both are present.
- The service must prevent directory traversal: subdirectory names and stored relative_path must not allow escaping the root_directory (no '..' segments, no absolute paths in relative_path).