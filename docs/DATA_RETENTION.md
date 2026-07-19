# Data Retention Policy (ROADMAP Phase 12)

> ⚠️ **PROTOTYPE — pending compliance-officer review.** The retention periods
> below are drawn from India's PMLA 2002 and RBI KYC/AML directions as a
> defensible starting point, but the actual policy for a production TraceX
> deployment must be set and signed off by the deploying institution's
> compliance function. This document records the *design intent* and the
> mechanism; it is not legal advice and is not the institution's policy of
> record.

## Regulatory anchors (India)

- **PMLA 2002, §12** and the PML (Maintenance of Records) Rules — a reporting
  entity must **maintain records of transactions and of the identity of clients
  for five (5) years** from the date of the transaction / from the date of
  cessation of the business relationship (account closure).
- **RBI Master Direction on KYC** — KYC records retained for **five (5) years
  after the business relationship ends**.
- **STR/SAR filings and their supporting records** — retained for **five (5)
  years** from the date of filing with FIU-IND, and longer if the matter is
  under investigation or litigation (a **legal hold** overrides scheduled
  deletion).

The load-bearing rule for this system: **anything that could be evidence in a
money-laundering investigation is retained at least 5 years, and a legal hold
suspends deletion indefinitely.**

## Retention schedule by data category

| Data | Tables | Retention | Rationale |
| --- | --- | --- | --- |
| Customer / account KYC | `customers`, `accounts` | 5 years after relationship ends | PMLA §12 / RBI KYC |
| Transactions | `transactions` | 5 years from transaction date | PMLA record-keeping |
| Alerts & cases | `alerts`, `cases`, `case_*`, `evidence`, `notes` | 5 years after case closure | Supporting record for the disposition |
| STR/SAR reports | `reports` | 5 years after FIU-IND filing (`submitted_at`) | STR record-keeping; longer under legal hold |
| **Audit log** | `audit_log` | **≥ 5 years, never truncated ahead of the longest live retention** | Tamper-evident hash-chain — deleting a link breaks verifiability of everything after it (see below) |
| AI interactions | `ai_interactions` | 5 years (tie to the case) | Explains an AI-assisted decision on a case; part of that case's record |
| Detection feedback | `detection_feedback` | Retained with the case; verdicts also feed model governance | Model-lineage / precision evidence |
| Watchlist | `watchlist` | Until removed + 5 years (soft-delete, never hard-deleted) | Screening decision trail |
| Model runs | `model_runs` | Retain the lineage of any model that ever scored a live alert | ML governance — reproduce what a past alert was scored by |
| Ingestion log | `ingestion_log` | 5 years | Provenance of the data behind alerts |

## Mechanism & constraints

- **Soft-delete is the default** (`docs/DATA_SCHEMA.md` §0): domain rows are
  deactivated (`active=false`) / status-transitioned, not hard-deleted, so the
  record survives for its retention window while dropping out of active views.
- **The audit hash-chain constrains purging.** `audit_log` is an append-only
  SHA-256 chain (each row hashes the prior); deleting or editing any row breaks
  verification of every later row. Purging audit history is therefore only ever
  done by **whole-prefix truncation past the retention horizon** (oldest-first,
  never from the middle), and only for records past the *longest* live retention
  — never per-record.
- **Legal hold overrides the schedule.** A case (and its transitively linked
  transactions, alerts, evidence, notes, reports, audit rows) under
  investigation or litigation is exempt from scheduled deletion until the hold
  is lifted. Enforcing holds is a production concern not yet built — flagged
  here so it isn't forgotten.
- **PII minimization already in place:** the AI layer never persists customer
  names (decision 9 — `customer_id` only; names are rehydrated display-only),
  and the PII egress gate is fail-closed, so the retained AI records carry no
  additional PII beyond the identifiers.

## Not yet implemented (production follow-ups)

- An actual **retention/purge job** (scheduled truncation past the horizon with
  the hash-chain constraint above). Today nothing auto-deletes; data accumulates.
- **Legal-hold flagging** on cases to exempt them from any future purge.
- Encryption-at-rest / key-rotation policy for the PII columns
  (`docs/DATA_SCHEMA.md` PII map) — an infrastructure concern, out of app scope.
