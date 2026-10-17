# HarvestLedger

Problem 4 — Produce Procurement & Payout

A buying-centre application for recording produce deliveries, applying
effective-dated prices and moisture deductions, and generating weekly
farmer payouts with advance recovery.

## 1. Title and one-liner

- **HarvestLedger** — KJBN Labs internship, Problem 4 (Produce Procurement & Payout).
- A buying-centre application that records produce deliveries, applies
  effective-dated prices and moisture deductions, and generates weekly farmer
  payouts with advance recovery.

**Current milestone: M1 (domain model, constraints, migrations, seed data and
tests) is complete.** The M2 service/API layer is not implemented yet; see
[section 11](#11-known-limitations) and [section 8](#8-business-rules-and-assumptions).

## 2. Live links

- Frontend: <URL>
- Backend API: <URL>
- API documentation: <URL>
- Health endpoint: <URL>
- Test credentials, if authentication is implemented.
- Expected cold-start delay, if applicable.

## 3. Tech stack

| Layer | Technology |
|---|---|
| Backend | Django and Django REST Framework |
| Frontend | React, TypeScript and Vite |
| Database | PostgreSQL (target); SQLite is used for local M1 development |
| Tests | pytest, pytest-django and pytest-cov |
| Local environment | Docker Compose (not configured yet) |
| CI | GitHub Actions |
| Hosting | <actual providers> |

Explain any important technology choices briefly.

## 4. Architecture

Include:
- A component and request-flow diagram.
- A short folder overview.
- Where business rules live and why.
- How delivery snapshots and payout transactions work.

Request flow:
Frontend → API → Services → Django ORM → PostgreSQL

## 5. Running locally

Prerequisites: Python 3.11+ and Node.js (frontend, later milestones). The M1
backend was developed against the pinned versions in
`backend/requirements.txt` (Django 5.2.x, pytest, pytest-django, ruff).

Backend (from the repository root):

```bash
cd backend
python -m venv venv
venv/Scripts/activate            # Windows; use venv/bin/activate on POSIX
pip install -r requirements.txt
```

> Note: `backend/requirements.txt` is currently saved as UTF-16 and must be
> re-saved as UTF-8 before `pip install -r` works reliably.

Database, migrations and seed (SQLite for local M1 development):

```bash
python manage.py migrate          # applies procurement.0001_initial
python manage.py seed_data        # idempotent reference data
python manage.py seed_data        # re-running adds nothing
python manage.py runserver
```

The default database is `backend/db.sqlite3` (created by `migrate`, git-ignored).
PostgreSQL wiring (`docker-compose.yml`, `DATABASE_URL`) is a later-milestone
task; the `DATABASE_URL` currently in `.env` is not read by settings yet, so the
application always uses SQLite right now.

Environment variables: `.env` is git-ignored and is not yet consumed by
`config/settings.py`. `SECRET_KEY` is the Django development key; it must be
moved to the environment before any deployment.

## 5a. Deployment

Document:
- Providers used.
- Build and start commands.
- Environment variables and secrets.
- Migration and seed process.
- Provider configuration files.
- Manual dashboard steps.
- Redeployment process.
- Safe reseeding procedure.
- Database persistence and cold-start limitations.

## 6. Running tests and coverage

Run the M1 suite (the green gate) from `backend/`:

```bash
python -m pytest -m "not m2"
```

Run everything (M1 + the pending M2 rule tests):

```bash
python -m pytest
```

Run just the pending M2 rule tests, which fail by design until the M2 service
layer exists:

```bash
python -m pytest -m m2
```

Actual M1 status (verified on this checkout):

- `python -m pytest -m "not m2"` -> **94 passed, 28 deselected**.
- `python -m pytest -m m2` -> **28 failed** with `ModuleNotFoundError: No module
  named 'procurement.services'` (expected: M2 not built yet).
- `python manage.py check` -> no issues; `makemigrations --check` -> no drift.
- `python -m pytest tests/integration/test_seed.py` -> **6 passed**.

Unit tests cover the business clock, numeric precision and the demo manifest.
Integration tests cover deletion protection, admin guardrails, weekly policy,
seed idempotency, and the M2 business-rule contracts (prices, payouts,
corrections, delivery maths). Coverage is not measured yet — no `pytest-cov`
figure is claimed here.

## 7. API overview

> Not implemented yet. The endpoints below are the planned M2+ surface; no DRF
> routes exist at M1.

| Method | Endpoint | Purpose | Main error codes |
|---|---|---|---|
| POST | /api/v1/deliveries/preview/ | Preview calculation | 400, 404, 422 |
| POST | /api/v1/deliveries/ | Create delivery | 400, 404, 422 |
| POST | /api/v1/payouts/generate/ | Generate weekly draft | 400, 404, 409, 422 |
| POST | /api/v1/payouts/{id}/finalise/ | Finalise payout | 404, 409, 422 |

Add every implemented endpoint.
Explain pagination, filters and decimal-string responses.
Link the OpenAPI documentation.

## 8. Business rules and assumptions

At M1 the seven assignment rules are represented by the schema, constraints and
design documents. The executable rule logic arrives with the M2 service layer,
so the M2 tests below fail by design (`ModuleNotFoundError:
procurement.services`) until it exists.

| Rule | M1 status (schema/constraints) | M2 owner (services/) | Test |
|---|---|---|---|
| Effective-dated pricing | `PriceListEntry (crop_grade, effective_from)` unique; `price_per_kg > 0` | `pricing.resolve_price` | `test_prices.py` |
| Moisture deduction | `Crop.moisture_threshold` / `max_moisture` bounded 0..100 | `delivery.calculate_breakdown` | `test_delivery_math.py` |
| Frozen delivery breakdown | `Delivery.threshold_used`, `applied_price`, `price_list_entry`, `deduction_*`, `net_kg`, `amount`, `calculation_version` | `delivery.record_delivery` | `test_prices.py`, `test_payouts.py` |
| Weekly payout selection | `Payout` + partial unique `payout_one_draft_farmer_week`; Monday..Sunday bounds from `clock.week_bounds` | `payouts.build_weekly_payout` | `test_payouts.py`, `test_weekly_policy.py` |
| Advance recovery | `Advance` + `Farmer.outstanding_advance >= 0`; no `(farmer, given_on)` dedup key | `advances.post_advance`, `payouts.finalise_payout` | `test_payouts.py` |
| Immutability and corrections | note constraints (original required, positive magnitude, non-blank reason); `PayoutStatus` | `corrections.record_correction` | `test_corrections.py` |
| Delivery validation | `delivery_procurement_positive`, `delivery_note_requires_fields`, `delivery_accounting_matches_delivered` | `delivery.record_delivery` | `test_delivery_math.py`, `test_prices.py` |

### 8.1 Precision assumptions

Defined in `backend/procurement/precision.py` and applied per field in
`models.py`. All arithmetic uses `Decimal` with `ROUND_HALF_UP` (never float).

| Quantity | Scale | Example |
|---|---|---|
| Gross weight (kg) | 3 dp | `100.125` |
| Moisture / threshold / deduction % | 2 dp | `14.99` |
| Derived weight (deduction_kg, net_kg) | 5 dp | `1.00000` |
| Price / applied price (per kg) | 2 dp | `24.50` |
| Money (amounts, balances) | 2 dp | `2450.00` |

1. `DecimalField` rejects over-precise input via `full_clean()` (admin/forms);
   `save()` does not call `full_clean()`, so the M2 service layer must validate.
2. Money and derived weights are quantised with `ROUND_HALF_UP`; monetary
   results are stored at 2 dp (e.g. `2.50000 x 1.01 = 2.525 -> 2.53`).
3. `deduction_kg + net_kg == gross_weight_kg` exactly at 5 dp.

### 8.2 Weekly and correction grouping policy

Documented in `backend/procurement/clock.py`; a week is **Monday..Sunday**
inclusive, with `Payout.week_start` the Monday and `week_end` the Sunday.

1. At most one **DRAFT** payout per `(farmer, week_start)` — DB partial unique
   `payout_one_draft_farmer_week`.
2. There is deliberately **no** unconditional `(farmer, week)` unique: once a
   week is FINALISED/PAID, late or previously unassigned records can be paid via
   a supplementary payout for the same week.
3. Building an empty week returns no payout. Finalised payout totals and their
   included deliveries remain frozen.
4. A correction (credit/debit note) requires its original delivery to belong to
   a FINALISED or PAID payout and retains the original farmer. It is stamped with
   `accounting_date` = the IST business date it is recorded, **not** the original
   `delivered_on`; that date selects the target payout week. Credit notes add
   to payout gross; debit notes subtract from it. Each note is included once
   without changing the original.
5. Advance recovery is `min(outstanding_advance, 30% of gross_amount)`, rounded
   to money precision with `ROUND_HALF_UP`, and the remainder carries forward.
6. Multiple advances to one farmer on one date are allowed; `(farmer, given_on)`
   is **not** a deduplication key (see `scenarios.ADVANCE_DEDUPLICATION_NOTE`).
7. UNRESOLVED product decisions (intentionally deferred): intra-day cutoff,
   corrections against an already-PAID week, multiple supplementaries per
   farmer/week, whether external dates are guaranteed IST, and back-dating
   limits. These are listed in `clock.py`.

### 8.3 UTC/IST handling

- `USE_TZ = True`: audit timestamps (`created_at`, `recorded_at`,
  `finalised_at`, `paid_at`) are timezone-aware UTC instants.
- `TIME_ZONE = 'Asia/Kolkata'` (IST, UTC+05:30, no DST) is used only to derive
  **business dates** (`DateField`s: `delivered_on`, `accounting_date`,
  `week_start`, `week_end`).
- Business-date decisions must go through `procurement.clock` (`get_clock()`,
  `business_date()`), never the raw UTC date: 18:30 UTC is already the next day
  in IST. Tests pin the clock with `use_clock(FrozenClock(...))`.

## 9. Error handling and logging

Explain:
- Validation errors.
- Business-rule violations.
- State conflicts.
- Expected database conflicts.
- Unexpected failures and transaction rollback.

Show the actual error-response shape.

Document logging fields, levels, request IDs,
sensitive-data exclusions and hosted log access.

## 10. Reviewer aids

- **Seed:** `python manage.py seed_data` — deterministic and idempotent; creates
  3 crops, 5 grades, 3 fictional farmers (phones `0000000001`–`0000000003`) and
  10 effective-dated prices. Running it again reports the rows as *existing* and
  changes nothing.
- **Demo scenarios (M2):** declared in `backend/procurement/scenarios.py` —
  `multiple-weeks`, `moisture-boundaries`, `missing-rate`, `backdated-price`,
  `large-advance`, `finalised-and-corrections`. They are a specification for M2,
  not executed in M1.
- **Reviewer clock:** `procurement.clock` exposes `use_clock(FrozenClock(...))`
  for tests. There is intentionally no API endpoint to change the clock.
- **Safe reseeding:** the command is non-destructive (`get_or_create`), so it is
  safe to re-run at any time. To start clean, delete `backend/db.sqlite3` (it is
  git-ignored) and re-run `migrate` then `seed_data`.
- **Reproduce edge cases:** run `python -m pytest tests/integration/test_seed.py`
  for seed behaviour, and `python -m pytest -m m2` to see the pending M2 rules.

## 11. Known limitations

**M1 is complete; the rest is not built yet.**

- Core requirements still to implement (M2+): the service layer
  (`procurement/services/`) for pricing, delivery maths, advance posting, weekly
  payout generation and corrections; the DRF API; the React frontend; and the
  PostgreSQL/Docker wiring. The 28 `m2`-marked tests currently fail with
  `ModuleNotFoundError`.
- Design restrictions chosen deliberately: financial rows are never seeded;
  history FKs are `PROTECT` (only `CropGrade.crop` is `CASCADE`); prices are
  append-only in admin; there is no frontend clock-override endpoint.
- Unresolved product decisions listed in `clock.py` (intra-day cutoff,
  corrections against PAID weeks, multiple supplementaries, IST-input
  guarantee, back-dating limits).
- Deployment/hosting, coverage figures and live links are not available yet and
  are intentionally left as placeholders earlier in this README.

## 12. AI and third-party usage

- AI assistant: opencode (CLI coding agent) was used to draft and revise the M1
  backend files, tests and this documentation.
- Third-party code: only the standard Django project scaffold
  (`django-admin startproject` / `startapp`) and the pinned packages in
  `backend/requirements.txt`; no external templates or snippets were copied.

See [PROMPTS.md](PROMPTS.md) for the record of prompts actually used. It is
currently minimal — earlier entries must be transcribed from the author's real
session history and have not been invented here.
