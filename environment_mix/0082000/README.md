# ChEMBL Server — local MCP environment

This backend stores a local, query-optimized mirror of the ChEMBL domain (molecules/compounds, targets, assays, activities, documents and controlled vocabularies) plus a small computational cache for structure/descriptor utility calls. The main workflows are (1) read/search endpoints that filter by simple attributes (type/name/id) and return matching entities and (2) cheminformatics utility endpoints that compute canonicalization/standardization, descriptors, format conversions, and structural alerts with cached results.

Repository: https://github.com/JackKuo666/ChEMBL-MCP-Server
Homepage: https://smithery.ai/server/@JackKuo666/chembl-mcp-server

## Datastore

- `chembl_entities.json` — Canonical registry of primary ChEMBL entities addressable by a ChEMBL identifier. Used for ID lookup, description/official name utilities, and parent-child relationships across entity types. (18 rows; fields: ['id', 'chembl_id', 'entity_type', 'official_name', 'description_text', 'parent_entity_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'merged']
  - constraint: unique(chembl_id)
  - constraint: entity_type in enum
  - constraint: status in enum
  - constraint: parent_entity_id must reference an existing chembl_entities.id when not null
- `compound_structures.json` — Chemical structure and computed identifiers for molecules and related entities. Supports SMILES/InChI conversions, canonicalization/standardization, and structure-derived lookups. (18 rows; fields: ['id', 'entity_id', 'input_smiles', 'canonical_smiles', 'standardized_smiles', 'smiles_no_h', 'inchi', 'inchi_key', 'is_3d', 'svg_2d', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: unique(entity_id, status) where status='active'
  - constraint: canonical_smiles is required and length(canonical_smiles) between 1 and 20000
  - constraint: if inchi_key is not null then length(inchi_key) in (27, 28)
  - constraint: entity_id must reference chembl_entities.id
- `bio_catalog.json` — Queryable catalog for biological and classification entities accessed by name/type fields: assays, targets, target components/relations, protein classifications, organisms, tissues, cell lines, binding sites, ATC classes, GO slim, sources, xref sources, drugs/biotherapeutics and mechanisms/warnings/indications. (18 rows; fields: ['id', 'entity_id', 'catalog_type', 'type_value', 'name_value', 'level1', 'tax_id', 'extra', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: entity_id must reference chembl_entities.id
  - constraint: catalog_type in enum
  - constraint: status in enum
  - constraint: tax_id is null or (tax_id >= 1 and tax_id <= 2147483647)
- `activities.json` — Bioactivity measurements and supplementary activity data. Serves example_activity (by assay_chembl_id) and example_activity_supplementary_data_by_activity (by activity_chembl_id). (18 rows; fields: ['id', 'activity_entity_id', 'assay_entity_id', 'molecule_entity_id', 'target_entity_id', 'standard_type', 'standard_relation', 'standard_value', 'standard_units', 'pchembl_value', 'supplementary_data', 'extra', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'retracted']
  - constraint: unique(activity_entity_id)
  - constraint: activity_entity_id must reference chembl_entities.id
  - constraint: assay_entity_id must reference chembl_entities.id
  - constraint: standard_value is null or (standard_value >= 0)
- `service_metadata.json` — Operational metadata exposed by example_status and example_chembl_release; also stores cached computed descriptor/alert results keyed by canonical smiles for utility endpoints. (19 rows; fields: ['id', 'kind', 'chembl_version', 'release_date', 'service_name', 'service_status', 'message', 'cache_key', 'cache_payload', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired']
  - constraint: kind in enum
  - constraint: if kind='CHEMBL_RELEASE' then chembl_version is not null and release_date is not null
  - constraint: if kind='SERVICE_STATUS' then service_status is not null
  - constraint: if kind='SMILES_CACHE' then cache_key is not null

## Business rules enforced by the tools

- example_chembl_id_lookup(available_type,q) must search chembl_entities where entity_type maps from available_type and (chembl_id ILIKE q% OR official_name ILIKE %q% OR description_text ILIKE %q%).
- example_description_utils(chembl_id) returns chembl_entities.description_text for the matching chembl_id; if not found, return empty result set.
- example_official_utils(chembl_id) returns chembl_entities.official_name for the matching chembl_id; if not found, return empty result set.
- example_getParent(chembl_id) returns parent_entity_id resolved to its chembl_id; if the entity has no parent, return null/empty.
- example_activity(assay_chembl_id) must resolve assay_chembl_id -> chembl_entities.id (entity_type=ASSAY) then return activities filtered by assay_entity_id; only activities with status='active' are returned.
- example_activity_supplementary_data_by_activity(activity_chembl_id) must resolve activity_chembl_id -> chembl_entities.id (entity_type=ACTIVITY) then return activities.supplementary_data for that activity; if missing, return empty list.
- example_assay(assay_type) returns bio_catalog rows where catalog_type='ASSAY' and type_value equals assay_type and status='active'. Similar equality filtering applies for: drug_type, target_type, component_type, relationship_type, biotherapeutic_type, assay_class_type, description_type.
- Name-based endpoints (binding_site/site_name, cell_line/cell_line_name, tissue/tissue_name, xref_source/xref_name, compound_record/compound_name, compound_structural_alert/alert_name, document/journal, protein_classification/protein_class_name, mechanism/mechanism_of_action, go_slim/go_slim_term, drug_indication/mesh_heading, drug_warning/meddra_term, source/source_description, molecule_form/form_description) filter bio_catalog.name_value with case-insensitive match and return only status='active'.
- example_atc_class(level1) filters bio_catalog where catalog_type='ATC_CLASS' and level1 equals the provided level1.
- example_organism(tax_id) filters bio_catalog where catalog_type='ORGANISM' and tax_id equals the provided tax_id.
- SMILES/InChI utility endpoints must normalize input by computing canonical_smiles (or inchi_key for InChI) and may upsert a SMILES_CACHE row in service_metadata(kind='SMILES_CACHE') with expires_at in the future.
- example_smiles2svg and example_inchi2svg may return cached svg_2d from compound_structures when an entity exists; otherwise store result in SMILES_CACHE.cache_payload and return it.
- example_structuralAlerts(smiles) must return alerts from SMILES_CACHE if present and unexpired; otherwise compute, store in cache_payload.structural_alerts, and return.
- example_status returns the single active SERVICE_STATUS row; example_chembl_release returns CHEMBL_RELEASE rows ordered by release_date desc.