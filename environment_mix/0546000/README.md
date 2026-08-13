# Bluefin Social Console

Bluefin Social Console is a small Twitter-like integration service that tracks an authenticated session and the local working set of tweets, interactions, and follow relationships used by its TwitterAPI tools.

## Datastore

### `state.json` — single document
Holds the service’s current session context (credentials and authentication flag) plus the in-memory working data for tweets, comments, retweets, following, and counters so the tools can operate and keep continuity across calls.

- `username` — string
- `password` — string
- `authenticated` — boolean
- `tweets` — object
  each record in `tweets` has:
  - `id` — integer
  - `username` — string — one of alice, bob, carol, dave, eve, frank, john
  - `content` — string
  - `tags` — array
  - `mentions` — array
- `comments` — object
  each record in `comments` has:
  - `0` — array
    each record in `0` has:
    - `username` — string
    - `content` — string
  - `1` — array
    each record in `1` has:
    - `username` — string
    - `content` — string
  - `3` — array
    each record in `3` has:
    - `username` — string — one of dave, john
    - `content` — string
  - `4` — array
    each record in `4` has:
    - `username` — string
    - `content` — string
  - `9` — array
    each record in `9` has:
    - `username` — string
    - `content` — string
  - `11` — array
    each record in `11` has:
    - `username` — string
    - `content` — string
  - `16` — array
    each record in `16` has:
    - `username` — string
    - `content` — string
  - `21` — array
    each record in `21` has:
    - `username` — string — one of alice, frank
    - `content` — string
- `retweets` — object
  each record in `retweets` has:
  - `john` — array
  - `alice` — array
  - `bob` — array
- `following_list` — array
- `tweet_counter` — integer
- `random_seed` — integer
