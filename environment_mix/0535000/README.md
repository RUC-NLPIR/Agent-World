# HubSpot MCP — local MCP environment

This backend persists a synced subset of HubSpot CRM data (objects, their typed properties, and relationships) so the MCP tools can create/read/update/search/archive CRM entities and manage their associations. It also stores engagement-like activities (meetings, notes, tasks, calls, emails) as CRM objects and tracks communication subscription definitions plus per-contact preference/status updates.

Repository: https://github.com/shinzo-labs/hubspot-mcp
Homepage: https://smithery.ai/server/@shinzo-labs/hubspot-mcp

## Datastore

- `crm_objects.json` — All CRM records across standard and custom object types. Stores canonical fields for common types plus a JSON bag for arbitrary properties to support generic object CRUD/search tools. (34 rows; fields: ['id', 'portal_id', 'object_type', 'hubspot_object_id', 'custom_object_schema_id', 'archived', 'status', 'properties', 'properties_version', 'search_text', 'created_at', 'updated_at', 'hubspot_created_at', 'hubspot_updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(portal_id, object_type, hubspot_object_id)
  - constraint: properties_version >= 1
  - constraint: archived = (status = 'archived')
  - constraint: object_type = 'custom' implies custom_object_schema_id is not null
- `crm_object_properties.json` — Property definitions (metadata) per portal and object type, including enumeration options. Powers get/create *_property tools and validates writes/search filters. (32 rows; fields: ['id', 'portal_id', 'object_type', 'name', 'label', 'type', 'field_type', 'group_name', 'description', 'display_order', 'has_unique_value', 'hidden', 'form_field', 'options', 'archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(portal_id, object_type, name)
  - constraint: archived = (status = 'archived')
  - constraint: type = 'enumeration' implies options.length >= 0
  - constraint: type != 'enumeration' implies options.length = 0
- `crm_association_types.json` — Catalog of association types between pairs of object types. Supports crm_list_association_types and validation for association creation tools. (31 rows; fields: ['id', 'portal_id', 'from_object_type', 'to_object_type', 'association_category', 'association_type_id', 'label', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(portal_id, from_object_type, to_object_type, association_category, association_type_id)
  - constraint: association_type_id >= 1
- `crm_associations.json` — Edges between CRM objects (many-to-many). Supports create/list/archive association tools and object read tools that include associations. (30 rows; fields: ['id', 'portal_id', 'from_object_id', 'to_object_id', 'from_object_type', 'to_object_type', 'association_category', 'association_type_id', 'status', 'archived', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(portal_id, from_object_id, to_object_id, association_category, association_type_id)
  - constraint: archived = (status = 'archived')
  - constraint: association_type_id >= 1
  - constraint: from_object_id != to_object_id
- `communications_subscriptions.json` — Communication subscription definitions and per-contact subscription status/preferences. Supports communications_* tools. (32 rows; fields: ['id', 'portal_id', 'row_type', 'subscription_id', 'definition_name', 'definition_description', 'contact_object_id', 'status', 'legal_basis', 'legal_basis_explanation', 'archived', 'created_at', 'updated_at'])
  - lifecycle `row_type`: ['definition', 'contact_status']
  - constraint: unique(portal_id, row_type, subscription_id, contact_object_id)
  - constraint: row_type = 'definition' implies contact_object_id is null and status is null
  - constraint: row_type = 'contact_status' implies contact_object_id is not null and status is not null
  - constraint: contact_object_id references crm_objects.id and referenced crm_objects.object_type must be 'contacts'

## Business rules enforced by the tools

- All tool operations are tenant-scoped: every read/write must include an implicit portal_id, and queries must filter by portal_id.
- crm_create_* and crm_create_object must validate provided property names against crm_object_properties for the corresponding object_type when definitions exist; unknown properties may be allowed only if additionalProperties is permitted by the tool schema and the portal policy allows it.
- crm_update_* and crm_update_object must reject writes to properties whose definitions are archived or hidden when portal policy forbids hidden fields; clearing is represented by empty string in properties JSON.
- crm_archive_object and crm_archive_* must set crm_objects.status='archived' and crm_objects.archived=true; list/search tools must exclude archived unless archived=true is requested.
- crm_search_objects/crm_search_companies/crm_search_contacts/crm_search_leads and activity search tools must enforce limit ranges from schemas (1..100) and association listing limit ranges (1..500).
- Search filter evaluation must support operators EQ, NEQ, LT, LTE, GT, GTE, BETWEEN, IN, NOT_IN, HAS_PROPERTY, NOT_HAS_PROPERTY, CONTAINS_TOKEN, NOT_CONTAINS_TOKEN against crm_objects.properties; BETWEEN requires a two-value array, IN/NOT_IN require a non-empty values array or a single value that is treated as singleton.
- crm_batch_* tools must be atomic per input item: if one input fails validation, the service returns per-item errors but must not partially write an individual item (either its object row and its associations are created, or neither is).
- Association creation tools must validate (from_object_type,to_object_type,associationCategory,associationTypeId) exists and is active in crm_association_types for the portal_id; otherwise reject.
- crm_create_association/crm_batch_create_associations must upsert active associations: if an identical association exists archived, it is reactivated (status->active, archived=false).
- crm_archive_association/crm_batch_archive_associations must mark matching associations as archived; attempting to archive a non-existent edge is a no-op but should be reported as not found when strict mode is enabled.
- Object get tools with associations (e.g., crm_get_company associations=['contacts','deals']) must resolve associations by joining crm_associations and crm_objects and return only active, non-archived associated objects.
- meetings/tasks/notes/calls/emails CRUD tools map to crm_objects rows with object_type equal to their plural tool domain; required properties in schemas must be enforced on create and on update where schema marks them required.
- engagement_details_create/update must write a crm_objects row with object_type='engagements' and store the engagement payload in crm_objects.properties plus store metadata JSON under properties.metadata; associations.contactIds/companyIds/dealIds/ticketIds/ownerIds must be persisted as crm_associations edges to the corresponding crm_objects rows when present.
- communications_get_subscription_definitions returns rows where row_type='definition' filtered by archived flag.
- communications_get_preferences(contactId, subscriptionId?) reads communications_subscriptions where row_type='contact_status' for the contact; if subscriptionId provided, return only that subscription_id.
- communications_update_preferences must upsert a contact_status row for the (portal_id, subscription_id, contact_object_id) tuple and validate status/legalBasis enums.
- communications_unsubscribe_contact must set all contact_status rows for the contact to status='UNSUBSCRIBED' and set legal_basis to portalSubscriptionLegalBasis when provided; if a subscription has no existing row, create one with UNSUBSCRIBED.
- communications_subscribe_contact must set all contact_status rows for the contact to status='SUBSCRIBED' using the provided legal basis fields when present.
- products_batch_read and crm_batch_read_objects must support idProperty: when provided, interpret it as a property name marked has_unique_value=true in crm_object_properties; resolve requested IDs by matching crm_objects.properties[idProperty] and enforce uniqueness.