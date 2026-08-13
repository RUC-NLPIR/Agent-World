# SignalSure Account Console

SignalSure Account Console is a telecom account service that supports looking up customers and retrieving plan, line, device, and billing details to aid account servicing actions.

## Datastore

### `telecom_db.json` — single document

- `plans` — array
  each record in `plans` has:
  - `plan_id` — string — one of P1001, P1002, P1003, P1004, P1005
  - `name` — string — one of Basic Plan, Family Share, IoT Basic, Premium Plan, Unlimited Plus
  - `data_limit_gb` — number
  - `price_per_month` — number
  - `data_refueling_price_per_gb` — number
- `devices` — array
  each record in `devices` has:
  - `device_id` — string
  - `device_type` — string — one of phone, tablet
  - `model` — string
  - `imei` — string
  - `is_esim_capable` — boolean
  - `activated` — boolean
  - `activation_date` — string
  - `last_esim_transfer_date` — string
- `lines` — array
  each record in `lines` has:
  - `line_id` — string
  - `phone_number` — string
  - `status` — string — one of Active, Suspended
  - `plan_id` — string — one of P1001, P1002, P1003
  - `device_id` — string
  - `data_used_gb` — number
  - `data_refueling_gb` — number
  - `roaming_enabled` — boolean
  - `contract_end_date` — string — one of 2026-06-30, 2026-08-15, 2026-12-31, 2027-02-28
  - `last_plan_change_date` — string — one of 2024-08-20, 2024-10-05, 2024-12-15, 2025-01-10
  - `last_sim_replacement_date` — string — one of 2025-01-15, 2025-01-20
  - `suspension_start_date` — string — one of 2025-01-15, 2025-02-01
- `customers` — array
  each record in `customers` has:
  - `customer_id` — string — one of C1001, C1002, C1003, C1004
  - `full_name` — string — one of Emma Wilson, John Smith, Michael Lee, Sarah Johnson
  - `date_of_birth` — string — one of 1978-04-30, 1985-06-15, 1990-11-22, 1995-08-17
  - `email` — string
  - `phone_number` — string — one of 555-123-1002, 555-123-1003, 555-123-1004, 555-123-2002
  - `account_status` — string — one of Active, Pending Verification, Suspended
  - `created_at` — string
  - `goodwill_credit_used_this_year` — number
  - `line_ids` — array
  - `bill_ids` — array
  - `payment_methods` — array
    each record in `payment_methods` has:
    - `method_type` — string — one of Credit Card, Debit Card, PayPal
    - `account_number_last_4` — string — one of 1234, 1235, 5555, 5678
    - `expiration_date` — string — one of 06/2025, 06/2027, 12/2026
  - `address` — object
    each record in `address` has:
    - `street` — string
    - `city` — string — one of Anytown, Austin, Denver, Springfield
    - `state` — string — one of CA, CO, IL, TX
    - `zip_code` — string — one of 62701, 73301, 80203, 90210
  - `last_extension_date` — string
- `bills` — array
  each record in `bills` has:
  - `bill_id` — string — one of B1001, B1002, B1003, B1004, B1005, B1006
  - `customer_id` — string — one of C1001, C1002, C1003
  - `period_start` — string — one of 2025-01-01, 2025-02-01, 2025-03-01
  - `period_end` — string — one of 2025-01-31, 2025-02-28, 2025-03-31
  - `issue_date` — string — one of 2025-01-05, 2025-02-05, 2025-03-01
  - `total_due` — number
  - `due_date` — string — one of 2025-01-19, 2025-02-19, 2025-02-26, 2025-03-15
  - `status` — string — one of Disputed, Draft, Issued, Overdue, Paid
  - `line_items` — array
    each record in `line_items` has:
    - `description` — string
    - `amount` — number
    - `date` — string — one of 2025-01-05, 2025-02-05
    - `item_type` — string — one of Fee, Overage, Plan Charge
