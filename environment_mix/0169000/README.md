# RelayDesk Sales Orchestrator

RelayDesk Sales Orchestrator is a small automation service that simulates coordinating sales communications and CRM activity across Gmail, Slack, and HubSpot.

## Datastore

### `world.json` — object of 3 records keyed by identifier
Holds per-integration snapshots (gmail, slack, hubspot) of messages, channels, contacts, and deals so the service can read and write simulated external-system state.
Keys look like: gmail, slack, hubspot

- `account` — string
- `messages` — array
  each record in `messages` has:
  - `id` — string — nullable
  - `from_` — string
  - `to` — array
  - `cc` — array
  - `bcc` — array
  - `subject` — string
  - `body_plain` — string
  - `body_html` — null — nullable
  - `label_ids` — array
  - `is_read` — boolean
  - `is_starred` — boolean
  - `date` — integer
  - `internal_date` — integer
  - `ts` — string
  - `channel_id` — string — one of C_DEALS, C_GEN, C_LEADS, C_RENEWALS, C_SALES
  - `user_id` — string — one of U_AE1, U_AE2, U_AE3, U_BOT, U_MGR, U_SDR1
  - `text` — string
  - `thread_ts` — null — nullable
  - `reply_count` — integer
  - `is_bot` — boolean
  - `reactions` — array
    each record in `reactions` has:
    - `name` — string — one of eyes, heavy_plus_sign, tada, thumbsup, warning
    - `user_ids` — array
    - `count` — integer
- `bot_user_id` — string
- `channels` — array
  each record in `channels` has:
  - `id` — string — one of C_DEALS, C_GEN, C_LEADS, C_RENEWALS, C_SALES
  - `name` — string — one of deals, general, leads, renewals, sales
  - `is_private` — boolean
- `contacts` — array
  each record in `contacts` has:
  - `id` — string
  - `email` — string
  - `firstname` — string
  - `lastname` — string
  - `phone` — string
  - `company` — string
  - `jobtitle` — string
  - `lifecyclestage` — string — one of customer, evangelist, lead, marketingqualifiedlead, opportunity, salesqualifiedlead
  - `lead_score` — integer
  - `utm_source` — string — one of ad, event, organic, partner, referral, webinar
  - `utm_campaign` — string — one of ebook-downloads, partner-deal, q1-launch, retarget, spring-summit
  - `utm_medium` — string — one of cpc, email, organic, social, webinar
  - `industry` — string
  - `company_size` — string — one of 1-10, 1000+, 11-50, 201-500, 501-1000, 51-200
- `deals` — array
  each record in `deals` has:
  - `id` — string
  - `name` — string
  - `amount` — integer
  - `stage` — string — one of appointmentscheduled, closedlost, closedwon, contractsent, presentationscheduled, qualifiedtobuy
  - `contact_id` — string
