# Workspace Mirror Gateway

Workspace Mirror Gateway is a service that mirrors selected Notion workspace metadata and content so it can be retrieved, listed, searched, and queried via the Notion API surface it exposes.

## Datastore

### `notion_users.json` — list of 12 records
Holds Notion user profiles (people and bots) so the service can resolve user identities referenced elsewhere and support user retrieval/listing.

- `object` — string
- `id` — string
- `type` — string — one of bot, person
- `name` — string
- `avatar_url` — null — nullable
- `person` — object
  each record in `person` has:
  - `email` — string
- `bot` — object
  each record in `bot` has:
  - `type` — string
  - `workspace` — boolean

### `notion_self.json` — single document
Holds the token’s bot user record so the service can identify the acting integration account when interacting with Notion.

- `object` — string
- `id` — string
- `type` — string
- `name` — string
- `avatar_url` — null — nullable
- `bot` — object
  each record in `bot` has:
  - `type` — string
  - `workspace` — boolean

### `notion_databases.json` — list of 4 records
Holds Notion database definitions (metadata and property schemas) so the service can discover and query databases by id and understand their available properties.

- `object` — string
- `id` — string
- `created_time` — string
- `last_edited_time` — string
- `title` — array
  each record in `title` has:
  - `type` — string
  - `text` — object
    each record in `text` has:
    - `content` — string — one of Engineering Tasks, Incident Log, Product Roadmap, Project Tracker
    - `link` — null — nullable
  - `plain_text` — string — one of Engineering Tasks, Incident Log, Product Roadmap, Project Tracker
  - `annotations` — object
    each record in `annotations` has:
    - `bold` — boolean
    - `italic` — boolean
    - `strikethrough` — boolean
    - `underline` — boolean
    - `code` — boolean
    - `color` — string
- `description` — array
  each record in `description` has:
  - `type` — string
  - `text` — object
    each record in `text` has:
    - `content` — string
    - `link` — null — nullable
  - `plain_text` — string
  - `annotations` — object
    each record in `annotations` has:
    - `bold` — boolean
    - `italic` — boolean
    - `strikethrough` — boolean
    - `underline` — boolean
    - `code` — boolean
    - `color` — string
- `parent` — object
  each record in `parent` has:
  - `type` — string
  - `page_id` — string
- `url` — string
- `archived` — boolean
- `is_inline` — boolean
- `properties` — object
  each record in `properties` has:
  - `id` — string
  - `name` — string
  - `type` — string — one of date, multi_select, number, people, select, title
  - `title` — object
  - `select` — object
    each record in `select` has:
    - `options` — array
  - `people` — object
  - `date` — object
  - `number` — object
    each record in `number` has:
    - `format` — string
  - `multi_select` — object
    each record in `multi_select` has:
    - `options` — array

### `notion_pages.json` — list of 57 records
Holds Notion pages and their properties so the service can return page results for database queries and searches while preserving page metadata.

- `object` — string
- `id` — string
- `created_time` — string
- `last_edited_time` — string
- `created_by` — object
  each record in `created_by` has:
  - `object` — string
  - `id` — string
- `last_edited_by` — object
  each record in `last_edited_by` has:
  - `object` — string
  - `id` — string
- `cover` — null — nullable
- `icon` — object — nullable
  each record in `icon` has:
  - `type` — string
  - `emoji` — string — one of ⚙️, 🎨, 📄, 📚, 🔬, 🧑‍💼
- `parent` — object
  each record in `parent` has:
  - `type` — string — one of database_id, page_id, workspace
  - `workspace` — boolean
  - `database_id` — string
  - `page_id` — string
- `archived` — boolean
- `in_trash` — boolean
- `url` — string
- `properties` — object
  each record in `properties` has:
  - `id` — string
  - `type` — string — one of date, multi_select, number, people, select, title
  - `title` — array
    each record in `title` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `name` — string
  - `select` — object
    each record in `select` has:
    - `id` — string
    - `name` — string
    - `color` — string — one of blue, gray, green, orange, pink, purple, red, yellow
  - `people` — array
    each record in `people` has:
    - `object` — string
    - `id` — string
  - `date` — object
    each record in `date` has:
    - `start` — string
    - `end` — null — nullable
    - `time_zone` — null — nullable
  - `number` — integer
  - `multi_select` — array
    each record in `multi_select` has:
    - `id` — string
    - `name` — string
    - `color` — string — one of blue, gray, green, purple, red, yellow

### `notion_blocks.json` — list of 57 records

- `object` — string
- `id` — string
- `parent` — object
  each record in `parent` has:
  - `type` — string
  - `page_id` — string
- `created_time` — string
- `last_edited_time` — string
- `has_children` — boolean
- `archived` — boolean
- `in_trash` — boolean
- `type` — string
- `heading_1` — object
  each record in `heading_1` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string
  - `is_toggleable` — boolean
- `paragraph` — object
  each record in `paragraph` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string
- `heading_2` — object
  each record in `heading_2` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string
  - `is_toggleable` — boolean
- `to_do` — object
  each record in `to_do` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string
  - `checked` — boolean
- `bulleted_list_item` — object
  each record in `bulleted_list_item` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string
- `callout` — object
  each record in `callout` has:
  - `type` — string
  - `emoji` — string
- `code` — object
  each record in `code` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `caption` — array
  - `language` — string — one of bash, css, mermaid
- `divider` — object
  each record in `divider` has:
  - `color` — string
- `heading_3` — object
  each record in `heading_3` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string
  - `is_toggleable` — boolean
- `numbered_list_item` — object
  each record in `numbered_list_item` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string
- `quote` — object
  each record in `quote` has:
  - `rich_text` — array
    each record in `rich_text` has:
    - `type` — string
    - `text` — object
    - `plain_text` — string
    - `annotations` — object
  - `color` — string

### `notion_comments.json` — list of 13 records

- `object` — string
- `id` — string
- `parent` — object
  each record in `parent` has:
  - `type` — string — one of block_id, page_id
  - `page_id` — string
  - `block_id` — string
- `discussion_id` — string
- `created_time` — string
- `last_edited_time` — string
- `created_by` — object
  each record in `created_by` has:
  - `object` — string
  - `id` — string
- `rich_text` — array
  each record in `rich_text` has:
  - `type` — string
  - `text` — object
    each record in `text` has:
    - `content` — string
    - `link` — null — nullable
  - `plain_text` — string
  - `annotations` — object
    each record in `annotations` has:
    - `bold` — boolean
    - `italic` — boolean
    - `strikethrough` — boolean
    - `underline` — boolean
    - `code` — boolean
    - `color` — string
