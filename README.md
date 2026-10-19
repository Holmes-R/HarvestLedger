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

**Current milestone: M4 procurement UI.** M1 schema, M2 services and the M3
HTTP API are complete (527 passing tests). The React/TypeScript frontend is now a
working UI over the real API: delivery entry with a live preview, price history,
weekly payouts and the farmer ledger, plus farmer/crop/advance/correction forms.
See [section 7a](#7a-frontend-m4-ui).

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
| Tests | pytest, pytest-django and pytest-cov (backend); Vitest (frontend API client) |
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

### 5.1 Frontend

The UI is a React + TypeScript + Vite single-page app in `frontend/`. It talks to
the API directly (no API proxy) and adds no runtime dependencies beyond `react`
and `react-dom`. Point it at the backend with a git-ignored `frontend/.env`
(copy `frontend/.env.example`):

```
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Only the public API base URL belongs in `VITE_*`; database credentials and the
review key must never be exposed to the build. From `frontend/`:

```bash
npm install
npm run dev      # Vite dev server (default http://localhost:5173)
npm run lint     # ESLint (flat config, typescript-eslint)
npm run test     # Vitest unit tests for the API client and date helpers
npm run build    # tsc -b && vite build
```

`CORS_ALLOWED_ORIGINS` in `backend/.env` must include the dev-server origin (for
example `http://localhost:5173`) for browser calls to succeed.

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

Run only the M2 business-rule tests (marker `m2`), or only the M3 HTTP API tests
(marker `m3`). The markers are a selection convenience; there is no
`xfail`/`skip` anywhere, so a failing rule test fails the build rather than being
hidden.

```bash
python -m pytest -m m2
python -m pytest -m m3
```

Run just the API suite (real DRF request/response traffic against an isolated
PostgreSQL database, including the API01–API12 acceptance matrix):

```bash
python -m pytest tests/api
```

Measure coverage with the project's configured tooling (`pytest-cov`, from
`backend/`):

```bash
python -m pytest --cov=procurement --cov-report=term-missing
```

On 19 October 2026, with Python 3.11.9 and an isolated PostgreSQL test database,
`python -m pytest --reuse-db -q -ra --cov=procurement --cov-report=term --cov-report=json:coverage.json`
completed with **527 passed** (325 unit+integration, 202 API), no reported skips
or xfails, and 96% displayed whole-package coverage (2,191 statements, 97
missed). See [COVERAGE.md](COVERAGE.md) for the measured coverage scope.

Unit tests cover the business clock, numeric precision and the demo manifest.
Integration tests cover deletion protection, admin guardrails, weekly policy,
seed idempotency, concurrency, and the M2 business-rule contracts
(prices, payouts, corrections, delivery maths, advances, ledger). The API suite
drives the real router, serializers, middleware and M2 services over HTTP; its
`tests/api/test_acceptance_matrix.py` encodes the twelve acceptance cases
(API01–API12) one-to-one. The rule-to-service-to-test map for the API lives in
[`backend/procurement/api/README.md`](backend/procurement/api/README.md).

## 7. API overview

The M3 HTTP API is mounted under `/api/v1/`. It is a thin adapter over the M2
service layer: request shape (types, required fields, decimal precision,
references) is validated by DRF serializers; every business rule stays in
`procurement/services`. Interactive docs are served by drf-spectacular at
`/api/docs/`, with the raw schema at `/api/schema/`.

All responses use JSON. Money, weights and percentages are rendered as **decimal
strings** (never JSON floats) at the model field's scale —
`COERCE_DECIMAL_TO_STRING = True`.

**Authentication and permissions.** The API is explicitly **unauthenticated** for
this milestone: every endpoint sets `AllowAny` and there is no token, session or
user model, because the assignment does not specify identity or access control.
Write safety comes from the strict write contract (server-computed fields are
refused), not from a caller identity. This is a deliberate, documented scope
decision — the one exception is the demo-only reviewer-clock aid (§10.1), which is
off by default and gated by a shared key.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/v1/health/ | Liveness check |
| GET | /api/v1/farmers/ | List/search farmers (`search`, paginated) |
| POST | /api/v1/farmers/ | Create a farmer |
| GET | /api/v1/farmers/{id}/ | Farmer detail |
| PATCH | /api/v1/farmers/{id}/ | Update a farmer (`name`, `phone`, `village`, `bank_reference`) |
| GET | /api/v1/farmers/{id}/ledger/ | Bounded ledger page: typed event timeline + full-history summary (`from`/`to`/`event_type`) |
| GET | /api/v1/farmers/{id}/advance-reconciliation/ | Advance/recovery reconciliation |
| GET | /api/v1/crops/ | List crops (with `allowed_grades`) |
| POST | /api/v1/crops/ | Create a crop and its allowed grades |
| GET | /api/v1/crops/{id}/ | Crop detail (with `allowed_grades`) |
| PATCH | /api/v1/crops/{id}/ | Update crop moisture / allowed grades |
| GET | /api/v1/grades/ | List grades (`crop` filter) |
| GET | /api/v1/price-lists/ | List price entries (`crop_grade`, `crop` filters) |
| POST | /api/v1/price-lists/ | Append a price entry (service-validated) |
| POST | /api/v1/deliveries/preview/ | Preview a delivery calculation (writes nothing) |
| GET | /api/v1/deliveries/ | List deliveries (`farmer`, `kind`, `from`, `to`, `payout`) |
| POST | /api/v1/deliveries/ | Record a delivery |
| GET | /api/v1/deliveries/{id}/ | Delivery detail |
| PATCH | /api/v1/deliveries/{id}/ | Edit an unsettled delivery |
| POST | /api/v1/deliveries/{id}/corrections/ | Record a credit/debit note against that delivery |
| GET | /api/v1/advances/ | List advances (`farmer` filter) |
| POST | /api/v1/advances/ | Post an advance |
| GET | /api/v1/advances/{id}/ | Advance detail |
| GET | /api/v1/corrections/ | List credit/debit notes (`farmer`, `kind`, `original_delivery`) |
| POST | /api/v1/corrections/ | Record a credit/debit note |
| GET | /api/v1/corrections/{id}/ | Correction detail |
| POST | /api/v1/payouts/generate/ | Generate/extend a weekly DRAFT (`farmer`, `week_start`; empty week → `payout: null`) |
| GET | /api/v1/payouts/ | List payout statements (`farmer`, `status`, `from`, `to`) |
| GET | /api/v1/payouts/{id}/ | Payout statement (with member deliveries/corrections) |
| POST | /api/v1/payouts/{id}/finalise/ | Finalise a DRAFT payout (recovers advance) |
| POST | /api/v1/payouts/{id}/mark-paid/ | Settle a FINALISED payout |

**Pagination.** Every growing list — including the farmer ledger's event history —
is paginated with the standard page envelope (`count`, `next`, `previous`,
`results`). The default page size is **20** and the maximum is **100**: a larger
`?page_size=` is clamped, a non-positive or unparseable one falls back to the
default, and `?page=` walks the pages (an out-of-range page is `404`). No endpoint
returns an unbounded collection, and the ledger never nests an unbounded event
list inside its wrapper.

**Ordering.** Lists accept a whitelisted `?ordering=` (prefix `-` to reverse). The
field must be one the endpoint declares — an unknown field is `400` (`invalid`),
so an arbitrary ORM expression can never be injected. Every ordering is completed
with a unique id tie-breaker (the ledger adds an `event_type` tie-breaker too), so
the page sequence is deterministic.

**Filters.** All list filters are additive (AND), and date filters are
**inclusive on both ends** (`from` → `>=`, `to` → `<=`). A malformed type/date or a
reversed range (`from` after `to`) is `400`.

| List | Filters |
|---|---|
| farmers | `search` (name/phone/village) |
| grades | `crop` |
| prices | `crop`, `crop_grade` |
| deliveries | `farmer`, `kind`, `payout`, `from`, `to` |
| advances | `farmer`, `from`, `to` |
| payouts | `farmer`, `week`, `status`, `from`, `to` |
| corrections | `farmer`, `kind`, `original_delivery`, `from`, `to` |
| farmer ledger | `from`, `to`, `event_type` |

`week` is any day in the target week and is normalised to that week's Monday.

**Errors.** Every error uses one envelope:

```json
{"error": {"code": "STABLE_CODE", "message": "...", "details": {}, "request_id": "..."}}
```

Codes map to statuses deliberately: `400` malformed fields/types/precision
(`required`, `max_decimal_places`, `protected_field`, `unsupported_field`, ...);
`404` unknown resources (`*_not_found`, `not_found`); `409` duplicates and
forbidden state transitions (`payout_state_error`, `price_already_exists`,
`original_not_settled`, `original_changed`, `not_editable`,
`duplicate_crop_grade`, `grade_in_use`, `duplicate_crop`, `conflict`,
`referenced_record`); `422` domain rejection
of a well-formed request (`price_not_found`, `grade_not_allowed`,
`moisture_exceeds_maximum`, `future_delivery_date`, `invalid_moisture_bounds`,
`invalid_state`); `500` unexpected faults with a generic public message
(`internal_error`).

Known database conflicts surfaced after transaction rollback are mapped
deliberately rather than collapsed into one response: a uniqueness violation on a
named constraint becomes its specific `409` (`payout_one_draft_farmer_week` →
`payout_state_error`, `pricelist_grade_eff_unique` → `price_already_exists`,
`cropgrade_unique_crop_code` → `duplicate_crop_grade`); any other uniqueness
violation → `409 conflict`; a foreign-key/PROTECT violation → `409
referenced_record`; a check-constraint violation → `422 invalid_state`; NOT NULL
and other integrity failures are treated as `500` server faults, never
misreported as conflicts.

**Request IDs.** A well-formed client `X-Request-ID` is reused; otherwise one is
generated. It is returned on every response as `X-Request-ID` and in error
bodies, and is used in structured logs.

**Browser headers.** Allowed frontend origins may send `X-Request-ID` and the
optional `X-Test-Clock`/`X-Review-Key` headers. `X-Request-ID` is exposed to
browser JavaScript on responses. Origins remain explicitly configured by
`CORS_ALLOWED_ORIGINS`; CORS does not grant authentication or bypass the
reviewer-clock feature flag and key checks.

**Logging.** One structured JSON line per request
(`procurement/api/request_log.py`) with a real UTC timestamp, level, event,
request ID, method, safe path (never the query string), status, duration and the
non-sensitive numeric record IDs from the URL. Domain rejections log at
`WARNING` (`request.rejected`); unexpected faults log at `ERROR`
(`request.failed`) with the exception class and stack-frame module, function and
line locations. Exception messages, arguments, chained messages, source excerpts
and local variables are excluded because they may contain sensitive values.
Request/response bodies, credentials, banking references and review keys are
never logged.

**Write contract.** Writes are strict. Sending a server-computed field (for
example `amount`, `net_kg`, `applied_price`, `outstanding_advance`, or a
payout total) returns `400` with code `protected_field`; any field the endpoint
does not accept returns `400` with code `unsupported_field`. Such fields are
refused, never silently ignored by `read_only`. Input uses ISO-8601 dates
(`YYYY-MM-DD`); decimals must not exceed the model column's scale.

**Crop and grade management.** A crop response carries `allowed_grades` as a
list of `{id, code}` objects. `POST /crops/` and `PATCH /crops/{id}/` accept an
optional `allowed_grades` list of short codes (the same set, so a PATCH replaces
it): new codes are created and removed codes are deleted only when the grade has
no history. A grade referenced by a price entry or a delivery is **historical**;
removing it is refused with `409 grade_in_use` and the whole request (including
any new grades) rolls back. A crop's moisture configuration must satisfy
`0 <= moisture_threshold <= max_moisture <= 100` (`422 invalid_moisture_bounds`),
and a duplicate crop name is `409 duplicate_crop`. Changing a crop never touches
existing delivery snapshots (`threshold_used`, `applied_price`, `price_list_entry`,
`deduction_*`, `net_kg`, `amount` stay frozen).

**Financial fields are never writable.** `outstanding_advance` (and every other
computed money value) is refused with `400 protected_field` on farmer CRUD. There
are no delete routes and no price update/delete route: price history is
append-only (`PATCH`/`DELETE` on a price-list return `405`).

**Advances.** `POST /advances/` calls the M2 `advances.post_advance` service;
neither the serializer nor the view ever touches `outstanding_advance`. The
amount must be positive (`400 not_positive`) and within the column's precision
and capacity, and the farmer must be supplied and stored (`400` / `404
farmer_not_found`). A client-supplied balance or other computed field returns
`400 protected_field`. Advances are append-only: `GET /advances/{id}/` is
read-only (`PATCH`/`DELETE` → `405`), and the balance moves only through the
locking service. The same `(farmer, given_on)` is **not** a dedup key — several
advances may be posted on one day and each is counted once.

**Ledger.** `GET /farmers/{id}/ledger/` projects the M2 `ledger.build_farmer_ledger`
read model as a **bounded page of events plus an account summary**. `results` is a
single typed timeline — each row carries an `event_type`
(`DELIVERY`/`CORRECTION`/`ADVANCE`/`PAYOUT`), its business `date`, the signed
`amount` and the matching `delivery`/`advance`/`payout` object (the others `null`)
— so the growing history *is* the paginated collection, never an unbounded list
nested inside the wrapper. `?event_type=` narrows the timeline, `?from=`/`?to=`
are inclusive bounds on the event date, and `?ordering=`/`?page=`/`?page_size=`
apply as above. The `summary` (identity, `outstanding_advance`, `total_advances`,
`settled_earnings`, `total_recovered`, `draft_projection`, `unassigned_earnings`,
`total_recorded_amount`, `reconciliation`, `earnings_identity_holds`) always covers
the **full** history, so a page or window never distorts the balance; DRAFT
projections stay apart from settled recovery and no delivery is double counted
(`settled_earnings + draft_projection + unassigned_earnings ==
total_recorded_amount`).

**Deliveries.** `POST /deliveries/preview/` validates the input, resolves the
effective price and returns the whole breakdown (threshold used, applied price and
its `price_list_entry`, deduction percent, deduction kg, net kg, amount) with the
effective business `accounting_date`, writing nothing. `POST /deliveries/` takes
the original inputs only (`farmer`, `crop_grade`, `delivered_on`,
`gross_weight_kg`, `moisture_percent`) and recalculates authoritatively through
`delivery.record_delivery`; a forged `amount`, `deduction_kg`, `applied_price`,
`net_kg`, `price_list_entry` or membership field (`payout`) is refused with `400
protected_field`. `PATCH /deliveries/{id}/` recalculates and refreshes the DRAFT
payout, while a delivery in a FINALISED or PAID payout is immutable (`409
payout_state_error`). `POST /deliveries/{id}/corrections/` records a credit/debit
note against the delivery named in the URL: ownership, state and the signed total
are resolved and validated by `corrections.record_correction` (never trusted from
the client) and the original snapshot is preserved.

**Payouts.** A payout response is a **statement**: the stored `status`, the
Monday..Sunday `week_*` bounds, the server-computed `gross_amount`,
`advance_deduction` and `net_amount`, the `finalised_at`/`paid_at` timestamps,
and the exact `deliveries` currently attached to the week (procurement
deliveries and credit/debit notes together, each rendered with its frozen
breakdown). `POST /payouts/generate/` always returns the envelope
`{"payout": <statement or null>, "reason": <string or null>}`: a created or
extended DRAFT is `201` with the statement, while an **empty week** is a
successful no-op (`200`, `payout: null`, `reason: NO_ELIGIBLE_DELIVERIES`) that
invents no payout and leaves balances untouched. Repeated generation reuses the
same DRAFT and refreshes its membership; a delivery recorded after the week was
finalised gets a **supplementary** DRAFT. `finalise` is the only step that
recovers `min(outstanding_advance, 30% of gross)` (once, atomically), and
`mark-paid` is the only settlement (`FINALISED -> PAID`, never recovering
again); any other transition is `409 payout_state_error`. Client input can never
set membership, totals, status or a balance: `farmer`, `week_start` are the only
accepted generate fields (a forged `deliveries`/`status`/total is `400
protected_field`), there is no generic mutation route (list has no `POST`, the
statement has no `PATCH`/`DELETE`), and the finalised financial values are
frozen.

**OpenAPI schema.** The generated schema (`/api/schema/`, browsable at
`/api/docs/`) is the machine-readable contract and is kept in step with the
responses above. Every operation is tagged and summarised, request/response
bodies reference named components, and money/weight/percentage fields are
documented as decimal **strings** at their column scale (never JSON floats). It
describes the shared error envelope and its status families, the
pagination/ordering/filter parameters of every list (including that an unknown
ordering key is `400`), the empty-week payout success (`200`,
`reason: NO_ELIGIBLE_DELIVERIES`) alongside the `201` created statement, the
one-way `finalise`/`mark-paid` transitions (documented with no request body), and
the optional, demo-only reviewer-clock headers (`X-Test-Clock`/`X-Review-Key`,
§10.1) with their `403`/`400` rejection codes. Enums are shared named
components, so `kind` and `status` reuse a single component each instead of
diverging per endpoint. Regenerate and validate from `backend/`:

```bash
venv/Scripts/python.exe manage.py spectacular --validate --file schema.yaml
```

**Rule-to-service-to-test map.** Each API operation, the M2 service it delegates
to, and the tests that pin it are listed in
[`backend/procurement/api/README.md`](backend/procurement/api/README.md), which
also carries the API01–API12 acceptance matrix.

## 7a. Frontend (M4 UI)

A dependency-light client over the M3 API. It renders **decimal strings verbatim**
(never parses money/weight/percent into `number`), keeps the backend authoritative
for every computation, and reproduces the API's error envelope rather than hiding
it.

**Navigation.** A tiny hash router (`src/hooks/useHashRoute.ts`) — no routing
dependency — with four sections and deep links:

| Route | Screen |
|---|---|
| `#/deliveries` | Delivery entry: capture form, live `POST /deliveries/preview/` breakdown, recent-deliveries list |
| `#/deliveries/{id}` | Reusable delivery detail (frozen breakdown, payout link, "Add correction") |
| `#/prices` | Price history: effective-dated entries with crop/grade filters |
| `#/payouts` | Weekly payouts: generate a draft + statement list |
| `#/payouts/{id}` | Payout statement: member deliveries, `Finalise` / `Mark paid` |
| `#/ledger` | Farmer ledger: account summary + typed event timeline with `from`/`to`/`event_type` filters |

**Reusable pieces.** `DeliveryDetail` is shared by the delivery list, the payout
statement and the ledger (each row links to `#/deliveries/{id}` and, when a list
only carries an id, the component fetches `GET /deliveries/{id}/`). Supporting
forms are contextual modal panels — `FarmerForm`, `CropForm`, `AdvanceForm`,
`CorrectionForm` — not separate dashboards. There is one HTTP client
(`src/api/client.ts`) and one typed endpoint module (`src/api/endpoints.ts`).

**Shared API client.** `src/api/client.ts` is the single choke point for network
access, and `src/api/endpoints.ts` exposes one typed function per operation
(farmers, crops/grades, prices, advances, delivery
preview/create/retrieve/update, corrections, payout
list/retrieve/generate/finalise/mark-paid, and the farmer ledger). It:

- reads the base URL from `VITE_API_BASE_URL` (`frontend/.env`, placeholder in
  `frontend/.env.example`) and only ever calls that base — an absolute `next`
  URL outside it is refused (`invalid_request_url`);
- keeps **every decimal a string** (no numeric coercion of money/weight/percent);
- serialises dates to the API contract (`toApiDate` → `YYYY-MM-DD`, reduced to the
  IST calendar date) and rejects input the API could never accept;
- handles **pagination explicitly** — a typed `Page<T>` plus `api.page()` and
  `iteratePages`/`collectPages` crawlers that follow the absolute `next` link and
  stop at a bounded `maxPages`;
- parses the shared **error envelope** into a typed `ApiError` (code, status,
  `details` with per-field messages, and the request id);
- preserves the **request id** — generated (well-formed) or supplied, sent as
  `X-Request-ID`, and read back from the response header or error body;
- handles **network errors, aborts and non-JSON bodies safely** (a non-JSON
  success returns `undefined`; a non-JSON error falls back to a status-derived
  envelope);
- supports **cancellation** through an `AbortSignal` (`useAsync` passes one and
  aborts in-flight loads on deps change/unmount);
- **never retries automatically**, and refuses to send a server-computed
  financial field (`protected_payload`) — `amount` is the advance principal on
  `POST /advances/` but computed everywhere else, so the guard is path-aware;
- on a network failure, abort or `5xx` for a write, reports the outcome as
  **`unknown`** rather than assuming nothing was saved, and attaches
  `error.reconciliation` (method, path, request id, `safeToRetry`, guidance) so
  the UI states the write may have applied and to re-check before retrying; the
  `ErrorBanner` surfaces that warning next to the operation.

Tests (`src/api/*.test.ts`, `src/util/dates.test.ts`) stub `fetch` and pin URL
construction, decimal preservation, date serialisation, page following, envelope
parsing, request-id handling, cancellation, the protected-field guard, and the
no-retry / unknown-outcome behaviour for failed writes.

**Decisions and assumptions.**

1. **No new dependencies.** React 19 + `react-dom` only; navigation, state and
   formatting are hand-rolled to keep the scaffold as delivered.
2. **Decimals stay strings.** Inputs are validated for scale (`src/util/decimal.ts`)
   and posted as strings; the API's returned strings are displayed as-is.
3. **Ids resolve to names client-side.** Delivery/advance/correction reads return
   `farmer` as an id and a grade id only, so lists resolve labels from small
   cached lookups (`src/api/lookups.ts`); payouts already embed `farmer_name`.
4. **Correction notes are nullable.** The schema marks some `Delivery` fields
   non-null, but they are `null` on credit/debit notes, so the detail view treats
   them as optional and shows kind-specific fields.
5. **Timestamps are shown as received** (ISO-8601 with a `+05:30` offset, not
   `Z`) via `src/util/dates.ts`.
6. **Editability is discovered from responses.** A delivery has no payout-status
   field, so the UI does not pre-judge editability; a refused write surfaces the
   API's `409 payout_state_error`/`not_editable`.
7. **Demo clock is gated and opt-in.** The header control only adds
   `X-Test-Clock`/`X-Review-Key` when a reviewer fills it in; the key lives in
   memory/`sessionStorage` and is never compiled into the bundle (see §10.1).
8. **Verification is lint + typecheck + build + a real-API smoke**, because the
   scaffold ships no test runner. `npm run build` fails the build on any
   `tsc -b` type error (`verbatimModuleSyntax`, `erasableSyntaxOnly`,
   `noUnusedLocals`) and `npm run lint` is clean.

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

The API status map and response envelope are documented in §7 above. Every
unmatched `/api/v1/` route returns a JSON `404 not_found` envelope with a
matching `X-Request-ID`. Unexpected faults return a generic public `500`; the
structured server log retains the request ID, exception class and safe frame
locations without exception text. Financial writes remain transactionally
rolled back when a service raises.

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
  for tests. A **demo-only, gated** HTTP aid can pin the *business* clock for a
  single request — see [10.1 Reviewer clock aid](#101-reviewer-clock-aid-demo-only).
- **Safe reseeding:** the command is non-destructive (`get_or_create`), so it is
  safe to re-run at any time. To start clean, drop and recreate the database,
  then run `migrate` and `seed_data`.
- **Reproduce edge cases:** run `python -m pytest tests/integration/test_seed.py`
  for seed behaviour, `python -m pytest tests/integration/test_concurrency.py`
  for the locking guarantees, and `python -m pytest -m m2` for the M2 rules.
- **Coverage:** [COVERAGE.md](COVERAGE.md) records the command and the
  business-rules vs overall figures.

### 10.1 Reviewer clock aid (demo-only)

Purpose: let a reviewer run the same request against a chosen business date
without touching system time, so date-dependent behaviour (future-delivery
rejection, weekly payout grouping around a week boundary) can be demonstrated on
a hosted demo.

Configuration (environment only; never hard-coded, never committed):

| Variable | Default | Meaning |
|---|---|---|
| `ALLOW_REVIEW_CLOCK` | `false` | Master switch; the aid is off unless this is `true`. |
| `REVIEW_CLOCK_KEY` | *(empty)* | Shared secret the caller must present. An empty key disables authorisation. |

Placeholders (see `backend/.env.example`):

```
ALLOW_REVIEW_CLOCK=false
REVIEW_CLOCK_KEY=<set-a-demo-only-secret>
```

Usage, only when enabled **and** the key matches:

```
POST /api/v1/deliveries/preview/
X-Review-Key: <the-review-key>
X-Test-Clock: 2026-12-31T23:00:00+05:30
```

The response includes the `business_date` the calculation used (normally the real
IST date; the override date when authorised). Behaviour:

- The override is **request-local** (a `contextvars` override). It never changes
  global/system time or any shared service state; two concurrent requests with
  different `X-Test-Clock` values each see their own business date.
- **Audit timestamps** (`created_at`, `recorded_at`, `finalised_at`, `paid_at`)
  and **request-log timestamps** always use real time.
- `X-Test-Clock` must be a **timezone-aware ISO-8601** instant; a naive or
  malformed value is rejected.

Documented errors (same envelope as every other error):

| Condition | HTTP | `error.code` |
|---|---:|---|
| `X-Test-Clock` sent while `ALLOW_REVIEW_CLOCK=false` | 403 | `review_clock_disabled` |
| Enabled but `X-Review-Key` missing or wrong | 403 | `review_clock_unauthorized` |
| Timestamp malformed or timezone-naive | 400 | `review_clock_invalid` |

The review key and header values are never logged or echoed.

**Demo-only:** there is no production bypass. Leave `ALLOW_REVIEW_CLOCK=false`
and `REVIEW_CLOCK_KEY` blank everywhere except a throwaway demo deployment, and
never commit a real value. Tests pin the clock in-process with
`use_clock(FrozenClock(...))`; this header aid exists purely so a reviewer can
demonstrate date-dependent rules on a hosted demo where process-level injection
is not available.

## 11. Known limitations

**M1 schema, M2 services, the M3 HTTP API and the M4 procurement UI are
implemented** (527 backend tests passing; see [COVERAGE.md](COVERAGE.md)). The
frontend is verified by `npm run lint` and `npm run build` plus a live-API smoke
run; it has no automated test runner of its own.

1. The **API is unauthenticated** by design (every route is `AllowAny`; no user
   model). It must be placed behind authentication/authorisation before it is
   exposed beyond a demo. The reviewer-clock aid is off by default and is the
   only keyed surface.
2. Not implemented at this milestone: production hosting/Docker wiring and CI.
   The frontend is a functional UI over the API with **focused unit tests for the
   shared API client and date helpers** (`npm test`), but no component or
   end-to-end browser tests, and there is no edit/delete affordance for
   already-finalised financial records (by design — the API refuses those
   writes).
3. Deployment, hosting, live links and CI are not available yet and are left as
   placeholders earlier in this README.
4. Concurrency is proven only against a single PostgreSQL instance with
   `select_for_update()`; there is no distributed-lock layer for a future
   multi-database topology (not required by the assignment). The concurrency
   tests are the only place the suite relies on real row locking.
5. The reviewer database `HarvestDB` has not been migrated to
   `0002_farmer_indian_mobile` (historical rows are preserved); a database whose
   `phone` values predate the Indian-mobile rule will reject that migration until
   the data is corrected.
6. Unresolved product decisions listed in `clock.py` (intra-day cutoff,
   corrections against PAID weeks, multiple supplementaries per farmer/week,
   external-date IST guarantee, back-dating limits) remain intentionally
   deferred rather than invented.
7. `requirements.txt` is UTF-16 LE (with BOM); edit it with an editor that
   preserves that encoding, or re-save it as UTF-16 before `pip install -r`.

## 12. AI and third-party usage

- AI assistant: opencode (CLI coding agent) was used to draft and revise the M1
  backend files, tests and this documentation.
- Third-party code: only the standard Django project scaffold
  (`django-admin startproject` / `startapp`) and the pinned packages in
  `backend/requirements.txt`; no external templates or snippets were copied.

See [PROMPTS.md](PROMPTS.md) for the record of prompts actually used.
