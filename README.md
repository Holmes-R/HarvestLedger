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

**Current milestone: M2 service layer.** M1 schema and M2 services are present.
The Part 1 validation and Part 2 correction, recovery and payout policies have
regression coverage. HTTP endpoints (M3) and the procurement UI (M4) are
pending; see [section 11](#11-known-limitations).

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
| Database | PostgreSQL for development and tests |
| Tests | pytest, pytest-django and pytest-cov |
| Local environment | PostgreSQL service; Docker Compose is not configured |
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

Prerequisites: Python 3.11+, PostgreSQL 17 (the verified local version), and
Node.js for the frontend scaffold. Install the pinned backend
dependencies from `backend/requirements.txt` (UTF-8).

Backend (from the repository root):

```bash
cd backend
python -m venv venv
venv/Scripts/activate            # Windows; use venv/bin/activate on POSIX
python -m pip install -r requirements.txt
```

Create a **local-only** PostgreSQL role and two separate databases. For example,
in an administrator `psql` session on `127.0.0.1`:

```sql
CREATE ROLE harvestledger_local LOGIN CREATEDB;
\password harvestledger_local
CREATE DATABASE harvestledger_dev OWNER harvestledger_local;
CREATE DATABASE harvestledger_test OWNER harvestledger_local;
```

Copy `backend/.env.example` to the git-ignored `backend/.env` and set its
`PGPASSWORD` to that role's local password. The example selects
`127.0.0.1:5432`, `harvestledger_dev` for ordinary commands and
`harvestledger_test` for pytest. It disables SSL/channel binding **only for the
local server**; the settings default to requiring both when those two options
are omitted. `config.settings` reads `.env` with the declared `django-environ`
dependency; `DATABASE_URL` is not the configured input.

Before migrations or tests, verify that `PGHOST` is local and that
`PGTESTDATABASE` differs from `PGDATABASE`. Never use the reviewer/hosted
database for tests. From `backend/`, run:

```bash
python manage.py check
python manage.py migrate
python manage.py seed_data
python -m pytest --reuse-db
python manage.py runserver
```

The `TEST.NAME` setting reads `PGTESTDATABASE` (or defaults to
`test_<PGDATABASE>`). `--reuse-db` reuses that isolated test database after its
first creation. The local role needs `CREATEDB` for a fresh pytest database.
`SECRET_KEY` is still a development key and must move to a secret store before
deployment.

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

Run everything (M1 regression + M2 business rules):

```bash
python -m pytest
```

Run only the M2 business-rule tests (marker `m2`). The marker is a selection
convenience; there is no `xfail`/`skip` anywhere, so a failing rule test fails
the build rather than being hidden.

```bash
python -m pytest -m m2
```

Measure coverage with the project's configured tooling (`pytest-cov`, from
`backend/`):

```bash
python -m pytest --cov=procurement --cov-report=term-missing
```

On 18 October 2026, with Python 3.12.14 and isolated local PostgreSQL 17.5,
`python -m pytest --reuse-db -q -ra --cov=procurement --cov-report=term --cov-report=json:.venv/part2_checks/final_coverage.json`
completed with **325 passed**, no reported skips or xfails, and 96% displayed
whole-package coverage (1,119 statements, 50 missed). The separately executed
Part 1 and Part 2 verification probes passed 43 and 12 cases respectively.
The Part 2 probes are also tracked as independent regressions. See
[COVERAGE.md](COVERAGE.md) for the measured coverage scope.

Unit tests cover the business clock, numeric precision and the demo manifest.
Integration tests cover deletion protection, admin guardrails, weekly policy,
seed idempotency, concurrency, and the M2 business-rule contracts
(prices, payouts, corrections, delivery maths, advances, ledger).

## 7. API overview

The M3 HTTP API is mounted under `/api/v1/`. It is a thin adapter over the M2
service layer: request shape (types, required fields, decimal precision,
references) is validated by DRF serializers; every business rule stays in
`procurement/services`. Interactive docs are served by drf-spectacular at
`/api/docs/`, with the raw schema at `/api/schema/`.

All responses use JSON. Money, weights and percentages are rendered as **decimal
strings** (never JSON floats) at the model field's scale —
`COERCE_DECIMAL_TO_STRING = True`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/v1/health/ | Liveness check |
| GET | /api/v1/farmers/ | List/search farmers (`search`, paginated) |
| POST | /api/v1/farmers/ | Create a farmer |
| GET | /api/v1/farmers/{id}/ | Farmer detail |
| GET | /api/v1/farmers/{id}/ledger/ | Full reconciled ledger |
| GET | /api/v1/farmers/{id}/advance-reconciliation/ | Advance/recovery reconciliation |
| GET | /api/v1/crops/ | List crops (read-only) |
| GET | /api/v1/crops/{id}/ | Crop detail |
| GET | /api/v1/grades/ | List grades (`crop` filter) |
| GET | /api/v1/prices/ | List price entries (`crop_grade` filter) |
| POST | /api/v1/prices/ | Add a price entry (service-validated) |
| POST | /api/v1/deliveries/preview/ | Preview a delivery calculation (writes nothing) |
| GET | /api/v1/deliveries/ | List deliveries (`farmer`, `kind`, `from`, `to`, `payout`) |
| POST | /api/v1/deliveries/ | Record a delivery |
| GET | /api/v1/deliveries/{id}/ | Delivery detail |
| PATCH | /api/v1/deliveries/{id}/ | Edit an unsettled delivery |
| GET | /api/v1/advances/ | List advances (`farmer` filter) |
| POST | /api/v1/advances/ | Post an advance |
| GET | /api/v1/advances/{id}/ | Advance detail |
| GET | /api/v1/corrections/ | List credit/debit notes (`farmer`, `kind`, `original_delivery`) |
| POST | /api/v1/corrections/ | Record a credit/debit note |
| GET | /api/v1/corrections/{id}/ | Correction detail |
| POST | /api/v1/payouts/generate/ | Generate/extend a weekly DRAFT (`farmer`, `week_start`) |
| GET | /api/v1/payouts/ | List payouts (`farmer`, `status`, `from`, `to`) |
| GET | /api/v1/payouts/{id}/ | Payout detail |
| POST | /api/v1/payouts/{id}/finalise/ | Finalise a DRAFT payout (recovers advance) |
| POST | /api/v1/payouts/{id}/pay/ | Settle a FINALISED payout |

**Pagination.** List endpoints return the standard page envelope
(`count`, `next`, `previous`, `results`) at 50 items per page; pass `?page=`.

**Filters.** Farmers support `?search=` (name/phone/village). Deliveries,
advances, corrections and payouts support the query parameters listed above.
An unknown `kind`/`status` or an unparseable date returns `400`.

**Errors.** Every error uses one envelope:
`{"error": {"code": "...", "message": "...", "fields": {...} | null}}`. Codes map
to statuses: 404 for `*_not_found`; 409 for state conflicts
(`payout_state_error`, `price_already_exists`, `original_not_settled`,
`original_changed`, `not_editable`, `empty_week`); 422 for well-formed requests
rejected by a domain rule (`price_not_found`, `grade_not_allowed`,
`moisture_exceeds_maximum`, `future_delivery_date`, `invalid_moisture_bounds`);
400 for input/validation errors. Unexpected failures return a generic `500`
(`internal_error`) with a correlation reference and never expose a traceback or
credential.

**Write contract.** Writes are strict. Sending a server-computed field (for
example `amount`, `net_kg`, `applied_price`, `outstanding_advance`, or a
payout total) returns `400` with code `protected_field`; any field the endpoint
does not accept returns `400` with code `unsupported_field`. Such fields are
refused, never silently ignored by `read_only`. Input uses ISO-8601 dates
(`YYYY-MM-DD`); decimals must not exceed the model column's scale.

## 8. Business rules and assumptions

Farmer phone numbers must be Indian mobile numbers: 10 ASCII digits starting
with 6, 7, 8, or 9. The optional `+91` prefix may be joined to the number or
followed by one space; one space may also separate the fifth and sixth mobile
digits. For example, `9876543210`, `98765 43210`, `+919876543210`, and
`+91 98765 43210` are accepted. Other prefixes, punctuation, and leading or
trailing whitespace are rejected by frontend validation, Django model
validation, and the PostgreSQL check constraint. The migration converts only
the three original named demo farmers' old placeholder numbers. Any other
invalid stored number must be corrected before the migration can finish.

The original assignment text is not checked into this repository. The rule map
below is the repository's summary of its procurement and payout requirements;
it should not be treated as a quotation of the original assignment. Effective
pricing, moisture deductions, snapshots, weekly payouts, advance recovery and
corrections are implemented by M1 constraints and M2 services. The exact
numeric precision, IST business clock, duplicate-date policy and supplementary
payout grouping are additional implementation assumptions documented below and
in `backend/procurement/services/README.md`.

| Rule | Schema/constraints status (M1) | Owner (services/) | Test |
|---|---|---|---|
| Effective-dated pricing | `PriceListEntry (crop_grade, effective_from)` unique; `price_per_kg > 0` | `pricing.resolve_price`, `pricing.create_price_entry` | `test_prices.py` |
| Moisture deduction | `Crop.moisture_threshold` / `max_moisture` bounded 0..100 | `delivery.calculate_breakdown` | `test_delivery_math.py` |
| Frozen delivery breakdown | `Delivery.threshold_used`, `applied_price`, `price_list_entry`, `deduction_*`, `net_kg`, `amount`, `calculation_version` | `delivery.record_delivery`, `delivery.preview_delivery`, `delivery.edit_delivery` | `test_prices.py`, `test_delivery_service.py`, `test_payouts.py` |
| Weekly payout selection | `Payout` + partial unique `payout_one_draft_farmer_week`; Monday..Sunday bounds from `clock.week_bounds` | `payouts.build_weekly_payout` | `test_payouts.py`, `test_weekly_policy.py` |
| Advance recovery | `Advance` + `Farmer.outstanding_advance >= 0`; no `(farmer, given_on)` dedup key | `advances.post_advance`, `payouts.finalise_payout`, `advances.assert_outstanding_reconciles` | `test_advances.py`, `test_payouts.py` |
| Immutability and corrections | note constraints (original required, positive magnitude, non-blank reason); `PayoutStatus` | `corrections.record_correction` | `test_corrections.py` |
| Delivery validation | `delivery_procurement_positive`, `delivery_note_requires_fields`, `delivery_accounting_matches_delivered` | `delivery.record_delivery` | `test_delivery_math.py`, `test_prices.py` |
| Finalisation / settlement states | `PayoutStatus` DRAFT -> FINALISED -> PAID; frozen payout fields | `payouts.finalise_payout`, `payouts.mark_payout_paid` | `test_payouts.py` |
| Read-only farmer ledger | (derived; no new schema) | `ledger.build_farmer_ledger` | `test_ledger.py` |
| Concurrency safety | row locks + fixed lock order (`locking.py`) | all services | `test_concurrency.py`, `test_advances.py`, `test_payouts.py`, `test_corrections.py` |

### 8.1 Precision assumptions

Defined in `backend/procurement/precision.py` and applied per field in
`models.py`. Arithmetic uses `Decimal`, never binary floats. Delivery amounts
and derived weights use `ROUND_HALF_UP`; the advance recovery cap uses
`ROUND_DOWN` so the recovered cents do not exceed the exact percentage limit.

| Quantity | Scale | Example |
|---|---|---|
| Gross weight (kg) | 3 dp | `100.125` |
| Moisture / threshold / deduction % | 2 dp | `14.99` |
| Derived weight (deduction_kg, net_kg) | 5 dp | `1.00000` |
| Price / applied price (per kg) | 2 dp | `24.50` |
| Money (amounts, balances) | 2 dp | `2450.00` |

1. `DecimalField` rejects over-precise input via `full_clean()` (admin/forms);
   `save()` does not call `full_clean()`, so M2 services validate input and
   calculated outputs against destination field capacity before writing.
2. Delivery money and derived weights are quantised with `ROUND_HALF_UP`;
   monetary results are stored at 2 dp (e.g. `2.50000 x 1.01 = 2.525 -> 2.53`).
   The advance recovery cap has a separate round-down rule.
3. `deduction_kg + net_kg == gross_weight_kg` exactly at 5 dp.

### 8.2 Weekly and correction grouping policy

Documented in `backend/procurement/clock.py`; a week is **Monday..Sunday**
inclusive, with `Payout.week_start` the Monday and `week_end` the Sunday.

1. At most one **DRAFT** payout per `(farmer, week_start)` — DB partial unique
   `payout_one_draft_farmer_week`.
2. There is deliberately **no** unconditional `(farmer, week)` unique: once a
   week is FINALISED/PAID, late or previously unassigned records can be paid via
   a supplementary payout for the same week.
3. Building an empty week returns `None`, creates no payout and leaves the
   outstanding advance unchanged. This is the repository's chosen interpretation,
   not an explicit assignment requirement for an `EMPTY_PAYOUT` error. Finalised
   payout totals and their included deliveries remain frozen.
4. A correction (credit/debit note) requires its original delivery to belong to
   a FINALISED or PAID payout and retains the original farmer. It is stamped with
   `accounting_date` = the IST business date it is recorded, **not** the original
   `delivered_on`; that date selects the target payout week. Credit notes add
   to payout gross; debit notes subtract from it. Each note is included once
   without changing the original. The service looks up the original by primary
   key, locks its persisted farmer and payout, then reloads and verifies the
   original before creating the note.
5. Advance recovery is `min(outstanding_advance, floor_to_cents(30% of
   gross_amount))` for a positive gross. The percentage cap rounds `ROUND_DOWN`
   to two decimal places: gross `100.05` permits at most `30.01`, yielding net
   `70.04` when the outstanding balance is sufficient. This prevents recovery
   from exceeding exactly 30% of gross. Any remainder carries forward; zero or
   negative gross recovers nothing.
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

- **Seed:** `python manage.py seed_data` — deterministic and idempotent. Creates
  reference data (3 crops, 5 grades, 3 fictional farmers with example phones
  `9000000001`–`9000000003`, 10 effective-dated prices) **plus a financial demo
  built through `procurement.services`**: advances (including two same-day
  advances to one farmer), deliveries across several weeks covering the moisture
  boundaries and an effective-date price change, a probed-but-not-persisted
  missing-rate example, draft/finalised/paid payouts, a correction note and its
  supplementary payout. Running it again reports every row as *existing*, adds
  nothing, reapplies no recovery and leaves balances and snapshots untouched.
- **Demo scenarios:** declared in `backend/procurement/scenarios.py` —
  `multiple-weeks`, `moisture-boundaries`, `missing-rate`, `backdated-price`,
  `large-advance`, `finalised-and-corrections`. They are a readable
  specification; `seed_data` executes a comparable subset through the services.
- **Reviewer clock:** `procurement.clock` exposes `use_clock(FrozenClock(...))`
  for tests. There is intentionally no API endpoint to change the clock.
- **Safe reseeding:** the command is non-destructive (`get_or_create`), so it is
  safe to re-run at any time. To start clean, drop and recreate the database,
  then run `migrate` and `seed_data`.
- **Reproduce edge cases:** run `python -m pytest tests/integration/test_seed.py`
  for seed behaviour, `python -m pytest tests/integration/test_concurrency.py`
  for the locking guarantees, and `python -m pytest -m m2` for the M2 rules.
- **Coverage:** [COVERAGE.md](COVERAGE.md) records the command and the
  business-rules vs overall figures.

## 11. Known limitations

**M1 schema and M2 services are implemented.** The Part 1 and Part 2 regressions
are covered by tests. The API and procurement UI are not built yet.

1. Not implemented at this milestone: the DRF API, the procurement workflow UI,
   and production hosting/Docker wiring. The frontend currently has a phone
   format form, but no procurement workflow or HTTP integration. Section 7 and
   the `api/v1` routes remain planned-only.
2. Deployment, hosting, live links and CI are not available yet and are left as
   placeholders earlier in this README.
3. Concurrency is proven only against a single PostgreSQL instance with
   `select_for_update()`; there is no distributed-lock layer for a future
   multi-database topology (not required by the assignment).
4. The reviewer database `HarvestDB` has not been migrated to
   `0002_farmer_indian_mobile` (historical rows are preserved); a database whose
   `phone` values predate the Indian-mobile rule will reject that migration until
   the data is corrected.
5. Unresolved product decisions listed in `clock.py` (intra-day cutoff,
   corrections against PAID weeks, multiple supplementaries per farmer/week,
   external-date IST guarantee, back-dating limits) remain intentionally
   deferred rather than invented.
6. `requirements.txt` is UTF-8; if a tool rewrites it as UTF-16, re-save it
   before `pip install -r`.

## 12. AI and third-party usage

- AI assistant: opencode (CLI coding agent) was used to draft and revise the M1
  backend files, tests and this documentation.
- Third-party code: only the standard Django project scaffold
  (`django-admin startproject` / `startapp`) and the pinned packages in
  `backend/requirements.txt`; no external templates or snippets were copied.

See [PROMPTS.md](PROMPTS.md) for the record of prompts actually used.
