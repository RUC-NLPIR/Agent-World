# Namecheap Domains -Search/Register — local MCP environment

This backend stores Namecheap-account domain inventory, contact sets, DNS host records, and TLD pricing needed to support domain search and registration workflows. The main workflows are: checking availability/pricing for a domain, registering a domain with contact data, and reading/managing an account’s domain list, domain details, contacts, and DNS hosts.

Repository: https://github.com/webdevtodayjason/namecheap-mcp
Homepage: https://smithery.ai/server/@webdevtodayjason/namecheap-mcp

## Datastore

- `accounts.json` — Represents a connected Namecheap account/credential set used to call Namecheap APIs and scope all domain resources. (12 rows; fields: ['account_id', 'namecheap_username', 'status', 'api_key_ref', 'default_client_ip', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(namecheap_username)
  - constraint: status in ('active','disabled','revoked')
  - constraint: default_client_ip is null or matches IPv4/IPv6 format
- `domains.json` — Domains owned in a connected Namecheap account plus cached metadata used for listing and detailed info. (34 rows; fields: ['domain_id', 'account_id', 'fqdn', 'sld', 'tld', 'status', 'auto_renew', 'whois_guard_enabled', 'nameservers', 'created_at_registrar', 'expires_at', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'pending_transfer', 'pending_delete', 'suspended']
  - constraint: unique(account_id, fqdn)
  - constraint: fqdn must be a valid domain name (punycode allowed)
  - constraint: tld must be lowercase ascii or punycode
  - constraint: expires_at is null or expires_at > created_at_registrar
- `domain_contacts.json` — Stores the contact set (registrant/admin/tech/billing) associated with a domain. Snapshotted from Namecheap and used for registration payloads. (35 rows; fields: ['contact_set_id', 'domain_id', 'status', 'registrant', 'admin', 'tech', 'billing', 'source', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'historical', 'pending_update']
  - constraint: for a given domain_id, at most one row may have status='current' (partial unique index)
  - constraint: registrant/admin/tech/billing must include required keys: FirstName, LastName, Address1, City, StateProvince, PostalCode, Country, Phone, Email (validated at API boundary)
  - constraint: source in ('synced_from_namecheap','provided_for_registration')
- `dns_hosts.json` — DNS host records for domains using Namecheap DNS (host records such as A/AAAA/CNAME/TXT/MX). (33 rows; fields: ['dns_host_id', 'domain_id', 'status', 'host', 'record_type', 'value', 'ttl', 'mx_pref', 'is_frozen', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: ttl is null or (ttl >= 60 and ttl <= 86400)
  - constraint: mx_pref is null or (mx_pref >= 0 and mx_pref <= 65535)
  - constraint: record_type='MX' implies mx_pref is not null
  - constraint: unique(domain_id, host, record_type, value, coalesce(mx_pref,-1)) where status='active'
- `tld_pricing.json` — Cached TLD pricing and availability-related metadata returned by Namecheap pricing endpoints; used when checking and registering domains. (29 rows; fields: ['tld_price_id', 'tld', 'currency', 'operation', 'duration_years', 'price', 'promo_price', 'is_premium_possible', 'effective_at', 'expires_at', 'source_account_id', 'created_at', 'updated_at'])
  - constraint: unique(tld, currency, operation, duration_years, coalesce(source_account_id,'-'), effective_at)
  - constraint: duration_years >= 1 and duration_years <= 10
  - constraint: price >= 0
  - constraint: promo_price is null or promo_price >= 0
- `domain_registration_orders.json` — Tracks attempted domain registrations initiated via the service, including availability checks, chosen term, and Namecheap order/transaction references. (28 rows; fields: ['order_id', 'account_id', 'fqdn', 'tld', 'term_years', 'add_whois_guard', 'contact_set_id', 'availability_result', 'pricing_snapshot', 'namecheap_order_id', 'namecheap_transaction_id', 'status', 'failure_code', 'failure_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'checking', 'ready', 'submitted', 'succeeded', 'failed', 'cancelled']
  - constraint: term_years >= 1 and term_years <= 10
  - constraint: unique(account_id, fqdn, status) where status in ('draft','checking','ready','submitted')
  - constraint: fqdn must be a valid domain name (punycode allowed)
  - constraint: status='succeeded' implies namecheap_order_id is not null or namecheap_transaction_id is not null

## Business rules enforced by the tools

- All read tools (get_domain_list, get_domain_info, get_domain_contacts, get_dns_hosts) must scope results by account_id derived from the connected credentials; cross-account reads are forbidden.
- check_domain must create or update a domain_registration_orders row in status 'checking' (or reuse an existing non-terminal order for the same account_id+fqdn) and persist availability_result; it may also upsert relevant tld_pricing rows used for the check.
- register_domain must only proceed when the associated order status is 'ready' (or can transition from 'draft'/'checking' after a successful availability check). It must transition the order to 'submitted' before calling Namecheap and then to 'succeeded' or 'failed' based on the response.
- On successful registration (order status -> 'succeeded'), the system must upsert a domains row for (account_id,fqdn) and set status='active', and set last_synced_at to now.
- get_domain_contacts must return the single 'current' domain_contacts row when present; if none exists or last_synced_at is stale, the implementation should sync from Namecheap and create a new 'current' contact set while demoting the previous one to 'historical'.
- get_dns_hosts must return only dns_hosts rows with status='active'; if last_synced_at is stale, the implementation should resync and soft-delete missing records by transitioning them to status='deleted' rather than hard deleting.
- get_tld_pricing must return the most recent non-expired tld_pricing rows per (tld,currency,operation,duration_years,source_account_id) and should refresh from Namecheap when expired or absent.
- Uniqueness constraints must be enforced at write time: domains unique per (account_id,fqdn); at most one current contact set per domain; dns_hosts uniqueness for active records per (domain_id,host,record_type,value,mx_pref).
- Status transitions must be validated exactly as defined in each collection lifecycle; invalid transitions must be rejected.
- Numeric constraints must be enforced: tld_pricing.duration_years and domain_registration_orders.term_years in [1,10]; dns_hosts.ttl in [60,86400] when provided; mx_pref in [0,65535] when provided; all prices >= 0.