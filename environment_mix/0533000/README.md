# Redis — local MCP environment

This backend models a Redis-compatible data service with multiple logical databases, storing keys of different Redis data types (string, hash, list, set, sorted set, stream, JSON, and vector blobs), plus RediSearch vector indexes. It also tracks server metadata, connected clients, and pub/sub subscriptions for operational tooling (INFO, CLIENT LIST) and supports lifecycle behaviors like TTL expiration and key renames.

Repository: https://github.com/redis/mcp-redis
Homepage: https://smithery.ai/server/@redis/mcp-redis

## Datastore

- `redis_databases.json` — Logical Redis databases within a single Redis server/cluster. Holds server-level metadata and per-DB configuration used by INFO/DBSIZE and as the parent for all keys/indexes. (12 rows; fields: ['id', 'db_number', 'name', 'status', 'redis_version', 'modules', 'config', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'read_only', 'disabled']
  - constraint: unique(db_number)
  - constraint: db_number >= 0
  - constraint: db_number <= 1024
  - constraint: name <> ''
- `redis_keys.json` — Key catalog and metadata for all stored Redis keys across supported data types. Payloads for each type are stored in a type-specific value table. (36 rows; fields: ['id', 'db_id', 'key_name', 'key_type', 'encoding', 'ttl_seconds', 'expires_at', 'status', 'approx_size_bytes', 'last_accessed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'deleted']
  - constraint: unique(db_id, key_name)
  - constraint: ttl_seconds is null OR ttl_seconds >= 1
  - constraint: expires_at is null OR expires_at >= created_at
  - constraint: approx_size_bytes is null OR approx_size_bytes >= 0
- `redis_values.json` — Type-specific value storage for Redis keys. Exactly one row per key_id storing the payload for its key_type (string/hash/list/set/zset/stream/json) and optional vector blob stored as a hash field value. (36 rows; fields: ['id', 'key_id', 'db_id', 'string_value', 'hash_value', 'list_value', 'set_value', 'zset_value', 'stream_value', 'json_document', 'created_at', 'updated_at'])
  - constraint: unique(key_id)
  - constraint: key_id references redis_keys.id ON DELETE CASCADE
  - constraint: db_id must equal (select db_id from redis_keys where id = key_id)
  - constraint: For a given key_id, only the corresponding value column for redis_keys.key_type may be non-null
- `redis_search_indexes.json` — RediSearch/FT indexes (including vector indexes on hashes). Supports listing indexes, retrieving index info, counting indexed keys, and creating a vector HNSW index over hash keys with a prefix. (12 rows; fields: ['id', 'db_id', 'index_name', 'index_type', 'prefix', 'vector_field', 'dim', 'distance_metric', 'status', 'last_built_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'ready', 'failed', 'deleted']
  - constraint: unique(db_id, index_name)
  - constraint: dim >= 1
  - constraint: dim <= 32768
  - constraint: prefix <> ''
- `redis_runtime_sessions.json` — Operational runtime metadata: connected clients and pub/sub subscriptions. Provides backing data for CLIENT LIST and subscribe/unsubscribe behaviors. (30 rows; fields: ['id', 'db_id', 'session_type', 'client_id', 'client_addr', 'client_name', 'channel', 'status', 'last_heartbeat_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed']
  - constraint: client_id is not null when session_type = 'client_connection'
  - constraint: channel is not null when session_type = 'pubsub_subscription'
  - constraint: unique(db_id, session_type, client_id) where session_type='client_connection' and status='active'
  - constraint: unique(db_id, session_type, channel, client_id) where session_type='pubsub_subscription' and status='active'

## Business rules enforced by the tools

- All tools operate against exactly one active redis_databases row; if multiple DBs exist, the service must have a configured default db_id and reject requests if that DB status is 'disabled'.
- dbsize returns count(*) of redis_keys where db_id=<default> and status='active' and (expires_at is null or expires_at > now()).
- type(key) returns redis_keys.key_type for an active, non-expired key_name in the default DB; returns null/none if not found.
- delete(key) sets redis_keys.status='deleted' and deletes the redis_values row (or relies on ON DELETE CASCADE); subsequent reads must behave as missing.
- expire(name, expire_seconds) requires expire_seconds >= 1 and key must exist and be active; sets ttl_seconds and expires_at=now()+expire_seconds, and updates updated_at.
- rename(old_key,new_key) requires old_key exists and active; new_key must not already exist active in the same db_id; updates redis_keys.key_name and updated_at, preserving key_id and value.
- scan_keys(pattern,count,cursor) must only return keys with status='active' and not expired; pattern applies to redis_keys.key_name with glob semantics; count must be 1..10000; cursor is an opaque integer state produced by the scan implementation.
- scan_all_keys(pattern,batch_size) repeatedly calls scan_keys until cursor=0; batch_size must be 1..10000.
- set(key,value,expiration) upserts redis_keys with key_type='string'; stores value in redis_values.string_value; if expiration provided it must be >=1 and sets ttl_seconds/expires_at, else clears ttl_seconds/expires_at.
- get(key) returns redis_values.string_value only if redis_keys.key_type='string' and key is active and not expired; otherwise returns an error consistent with the tool's behavior.
- hset(name,key,value,expire_seconds) upserts redis_keys with key_type='hash'; sets redis_values.hash_value[key]=value; expire_seconds if provided must be >=1 and sets key TTL fields.
- hget/hdel/hexists/hgetall require key_type='hash' and active/not expired; hdel removes the field; if the hash becomes empty the key may remain or may be deleted depending on implementation, but behavior must be consistent.
- set_vector_in_hash(name,vector_field,vector) requires key_type='hash'; vector must be an array of numbers; stored as base64 float32 blob in redis_values.hash_value[vector_field]; dim validation occurs during vector_search_hash against the target index dim.
- get_vector_from_hash(name,vector_field) reads and decodes the stored base64 float32 blob back to an array; errors if missing field or invalid encoding.
- lpush/rpush upsert key_type='list' and push value to left/right of redis_values.list_value; expire if provided must be >=1 and sets TTL fields.
- lpop/rpop remove and return first/last element; if list becomes empty the key may be deleted or kept as empty, but must remain consistent across operations; reads require active/not expired.
- lrange(name,start,stop) requires key_type='list'; supports negative indexes; must clamp to list bounds.
- llen(name) returns length of list_value for key_type='list'.
- sadd/srem/smembers require key_type='set'; sadd enforces uniqueness; expire_seconds if provided must be >=1 and sets TTL fields.
- zadd requires key_type='zset'; upserts member with score; expiration if provided must be >=1 and sets TTL; zrange(with_scores) returns members ordered by score then member; zrem removes member.
- xadd requires key_type='stream'; creates a new entry with a generated entry_id if not provided by the underlying Redis; expiration if provided must be >=1; stores as an appended object in stream_value.
- xrange(key,count) returns up to count most-recent (or earliest per implementation) entries from stream_value; count must be 1..10000.
- xdel deletes stream entry matching entry_id; if not found, returns a not-found style response consistent with Redis semantics.
- get_indexes returns all redis_search_indexes.index_name where db_id=<default> and status in ('creating','ready','failed') excluding 'deleted'.
- get_index_info(index_name) returns the redis_search_indexes row plus computed stats (e.g., indexed keys count) derived by counting redis_keys with key_name like prefix% and key_type='hash' and active/not expired.
- get_indexed_keys_number(index_name) returns the computed count of keys matching prefix and eligible for indexing; must return 0 if index is deleted or not found.
- create_vector_index_hash creates (or replaces only if same definition) a redis_search_indexes row with index_type='vector_hnsw_hash'; dim must be >=1; distance_metric must be one of COSINE/L2/IP; status transitions from creating->ready or creating->failed.
- vector_search_hash(query_vector,index_name,vector_field,k,return_fields) requires the index exists and is status='ready'; k must be 1..10000; query_vector length must equal index.dim; candidates are hash keys with key_name starting with index.prefix and containing the vector_field; results return top-k by similarity and include requested return_fields from hash_value when provided.
- client_list returns active redis_runtime_sessions where session_type='client_connection' for the default db_id.
- publish(channel,message) does not require persistence; implementation may optionally append to an internal stream, but must at least succeed and report number of subscribers as count of active pubsub_subscription sessions for that channel.
- subscribe(channel) creates an active redis_runtime_sessions row with session_type='pubsub_subscription' and channel; duplicate active subscriptions for same (db_id, channel, client_id) must be rejected or de-duplicated per constraints.
- unsubscribe(channel) closes (status='closed') the matching active pubsub_subscription session(s) for that channel and updates updated_at.