# Appwrite MCP Server — local MCP environment

This backend stores Appwrite-style database resources: databases, collections, their schema (attributes and indexes), and the documents that live inside collections. The primary workflows are provisioning databases/collections, evolving schema by creating/updating/deleting attributes and indexes, and CRUD operations over documents with validation against the active schema and indexes.

Repository: https://github.com/appwrite/mcp
Homepage: https://smithery.ai/server/@appwrite/mcp

## Datastore

- `databases.json` — Top-level logical databases (namespaces) that own collections. Supports create/get/list/update/delete lifecycle. (18 rows; fields: ['id', 'name', 'description', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted']
  - constraint: unique(name) where status != 'deleted'
  - constraint: name length between 1 and 128
  - constraint: status in ('active','deleting','deleted')
  - constraint: deleted_at is null unless status='deleted'
- `collections.json` — Collections (tables) within a database. Own attributes, indexes and documents. Supports create/get/list/update/delete. (18 rows; fields: ['id', 'database_id', 'name', 'description', 'document_security', 'enabled', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted']
  - constraint: foreign key(database_id) references databases(id) on delete restrict
  - constraint: unique(database_id, name) where status != 'deleted'
  - constraint: name length between 1 and 128
  - constraint: enabled in (true,false)
- `attributes.json` — Schema attributes (fields) for a collection. Supports create/get/list/update/delete across multiple attribute types (string, integer, float, boolean, datetime, email, url, ip, enum, relationship). (18 rows; fields: ['id', 'collection_id', 'key', 'type', 'required', 'default_value', 'array', 'min', 'max', 'format', 'enum_values', 'relationship', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted']
  - constraint: foreign key(collection_id) references collections(id) on delete restrict
  - constraint: unique(collection_id, key) where status != 'deleted'
  - constraint: key matches ^[A-Za-z_][A-Za-z0-9_]{0,63}$
  - constraint: array in (true,false)
- `indexes.json` — Secondary indexes on collections, including unique and fulltext-style indexes. Supports create/get/list/delete. (18 rows; fields: ['id', 'collection_id', 'key', 'type', 'attributes', 'orders', 'status', 'last_error', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['building', 'active', 'failed', 'deleting', 'deleted']
  - constraint: foreign key(collection_id) references collections(id) on delete restrict
  - constraint: unique(collection_id, key) where status != 'deleted'
  - constraint: key matches ^[A-Za-z_][A-Za-z0-9_]{0,63}$
  - constraint: length(attributes) between 1 and 32
- `documents.json` — Documents stored in collections. Supports create/get/list/update/delete with JSON data validated against collection attributes and relevant index/unique constraints. (20 rows; fields: ['id', 'collection_id', 'database_id', 'data', 'permissions', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(collection_id) references collections(id) on delete restrict
  - constraint: foreign key(database_id) references databases(id) on delete restrict
  - constraint: database_id must equal (select database_id from collections where collections.id = documents.collection_id)
  - constraint: data must be a JSON object (not array/scalar)

## Business rules enforced by the tools

- databases_create inserts a databases row with status='active', and must reject duplicate (name) among non-deleted databases.
- databases_list returns databases where status != 'deleted' by default; deleted records are only returned for internal/admin contexts.
- databases_get must reject access when the requested database status is 'deleted'.
- databases_update may update name/description only when status='active'; it must set updated_at.
- databases_delete transitions database.status active->deleting->deleted; it must refuse deletion if any child collection has status!='deleted' unless the implementation performs a cascading delete workflow that marks children deleting then deleted.
- databases_create_collection inserts a collections row with status='active' and unique(database_id,name) among non-deleted collections.
- databases_get_collection and databases_list_collections only return collections whose database_id matches the path/operation context; collection must not be 'deleted'.
- databases_update_collection may update name/description/enabled/document_security only when collection.status='active'; disabling a collection (enabled=false) must block document create/update operations.
- databases_delete_collection transitions collection.status active->deleting->deleted; it must refuse deletion if any index is building or if a background job is required to purge documents before marking deleted.
- All attribute create tools (create_string_attribute, create_integer_attribute, create_float_attribute, create_boolean_attribute, create_datetime_attribute, create_email_attribute, create_url_attribute, create_ip_attribute, create_enum_attribute, create_relationship_attribute) insert into attributes with type set accordingly and status='active'; key must be unique within the collection among non-deleted attributes.
- databases_get_attribute and databases_list_attributes return only attributes for the given collection; must exclude status='deleted'.
- All attribute update tools must only modify rows where attributes.status='active' and collection.status='active'; they must enforce type-specific constraints (e.g., enum requires enum_values).
- databases_delete_attribute transitions attributes.status active->deleting->deleted; it must refuse deletion if the attribute is referenced by any non-deleted index.attributes or if it is the key_on_related in a relationship config.
- databases_create_index inserts into indexes with status='building', then transitions to 'active' once index build completes; it must validate that each attributes[] entry references an existing attributes.key with status='active' in the same collection.
- databases_get_index and databases_list_indexes must return indexes filtered by collection_id and exclude status='deleted'.
- databases_delete_index transitions index.status active|failed|building->deleting->deleted; it must not allow delete when already deleted.
- databases_create_document inserts into documents with status='active' and validates documents.data against the active attributes for the collection: required fields present, types correct, min/max honored, and enum membership enforced.
- databases_get_document must ensure the document.collection_id and document.database_id match the request context and that document.status != 'deleted'.
- databases_list_documents returns documents filtered by collection_id (and database_id via join/denorm check), returning only status='active' unless explicitly asked for deleted (not exposed in current tool surface).
- databases_update_document updates documents.data (partial merge or full replace per implementation) only when collection.enabled=true and document.status='active'; it must re-validate the resulting document against current active attributes and enforce unique indexes.
- databases_delete_document transitions document.status active->deleted and sets deleted_at; it must not physically remove the row to preserve referential integrity for relationship attributes unless a separate purge process exists.
- Relationship attributes must reference an existing target collection (relationship.related_collection_id) and must not create invalid cycles unless relation_type permits; on_delete behavior must be one of: 'restrict','cascade','setNull' and enforced when deleting documents or collections.
- Index uniqueness enforcement: for each active unique index on a collection, the tuple of indexed attribute values across active documents must be unique; null handling follows Appwrite semantics (reject duplicates when all indexed fields are equal, including nulls, unless configured otherwise).
- All create/update/delete operations must update updated_at; delete operations must set deleted_at when status becomes 'deleted'.
- Hard FK integrity: collection_id, database_id references must exist and be non-deleted at the time of mutation; mutations must fail with a referential integrity error otherwise.