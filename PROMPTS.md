# Prompt record

Record of the prompts actually used with the AI assistant, and what each
produced. Entries are transcribed verbatim from the session; nothing here is
reconstructed or invented. Prompts from the earlier M1 session are not
reproduced because they were not captured verbatim — they are deliberately left
out rather than guessed at.

Tooling: [opencode](https://opencode.ai) CLI coding agent.

---

## Entry 1 — Farmer ledger + financial demo seed

> Implement a read-only farmer ledger that shows, for one farmer, every
> delivery and correction note, every advance, every payout with its status and
> the arithmetic that produced it, the current outstanding advance balance, and
> a reconciliation of that balance. It must not modify anything. Extend
> `seed_data` into a repeatable, idempotent demo that uses the service layer to
> produce advances (including two to a farmer on one day), deliveries across
> several weeks covering the moisture boundaries and an effective-date price
> change, a missing-rate example that must not be persisted, draft/finalised/paid
> payouts, a correction note and its supplementary payout. Re-running the seed
> must add nothing and must not change balances or frozen snapshots.

Produced:

- `backend/procurement/services/ledger.py` — `build_farmer_ledger(farmer)`
  returning read-only `FarmerLedger` dataclasses (deliveries, advances, payouts,
  outstanding balance, reconciliation).
- `backend/tests/integration/test_ledger.py` — 6 tests.
- `backend/procurement/management/commands/seed_data.py` — reference data plus a
  service-built financial demo.
- `backend/tests/integration/test_seed.py` — extended idempotency/integrity
  tests.

---

## Entry 2 — M2 review, verification and commit-ready deliverables

> Review M2 against every assignment business rule and the README. Run: all
> former pending M2 tests; M1 model and seed regression tests; additional
> concurrency tests using independent PostgreSQL connections and
> transaction-capable test fixtures; Django system checks; migration-drift
> checks; seed idempotency checks; coverage using the project's configured
> tooling. Ensure concurrency tests verify persisted balances, membership, and
> totals rather than merely checking that requests completed. Report
> business-rules coverage and overall backend coverage separately. Target at
> least 80% coverage on the business-rules layer, without weakening tests to
> raise the percentage. Commit-ready deliverables: actual service
> implementations; passing tests for all implemented rules; repeatable complete
> demo seed; coverage summary file; README rule-to-service-to-test mapping;
> numbered assumptions and genuine limitations; accurate PROMPTS.md entries.
> Review M2 markers: keep useful selection markers, but remove obsolete
> pending/xfail treatment for completed cases; unexpected passing xfails must
> not hide results. Report exact commands, results, remaining failures and
> whether M2 is complete. Do not claim API/UI functionality at this milestone.
> Do not commit or push automatically.

Produced:

- `backend/tests/integration/test_concurrency.py` — 3 concurrency tests over
  independent PostgreSQL connections asserting persisted balances, membership
  and totals.
- Removed obsolete "pending M2 / expected to fail" wording from the `m2` test
  modules and `scenarios.py`; kept the `m2` selection marker (no `xfail`/`skip`).
- `COVERAGE.md` — coverage command, business-rules vs overall results.
- README updates: test/coverage status, rule-to-service-to-test mapping,
  numbered limitations, demo/seed aids.
- This file.

---

## Entry 3 — M3 HTTP API over the service layer

> Start building it

> Continue if you have next steps, or stop and ask for clarification if you are
> unsure how to proceed.

Produced (all under `backend/`):

- `procurement/api/` — new DRF package: `errors.py` (unified error envelope,
  code→status map, `api_exception_handler`, `EmptyWeek`), `pagination.py`,
  `serializers.py` (request-shape validation + decimal-string rendering),
  `views.py`, `urls.py`.
- `config/settings.py` — `rest_framework`/`drf_spectacular`/`corsheaders`,
  `REST_FRAMEWORK`, `SPECTACULAR_SETTINGS`.
- `config/urls.py` — `/api/v1/` include, `/api/schema/`, `/api/docs/`.
- `tests/api/` — `test_reference.py`, `test_ledger_api.py`,
  `test_deliveries.py`, `test_advances.py`, `test_corrections.py`,
  `test_payouts.py`, `test_schema.py` (marker `m3`).
- `pytest.ini` — `m3` marker; README §7 rewritten with the endpoint table,
  pagination/filters, decimal-string responses and error contract.

---

## Entry 4 — M3 foundation and strict write contract

> Configure the M3 API foundation using the existing project structure. Add DRF,
> django-cors-headers, and drf-spectacular only if absent. Record dependencies
> in the project's existing dependency files. Configure versioned routes under
> /api/v1/, JSON responses, explicit permission/authentication defaults, decimal
> values serialized as strings, environment-configured allowed frontend origins,
> appropriate middleware ordering, OpenAPI integration. Keep Django admin
> working. Create request/response serializer conventions: explicit writable
> fields, separate input/output representations, ISO dates, decimal precision
> matching models/services, clear handling of missing/null/blank/unsupported
> fields. Explicitly reject attempts to write protected calculated fields; do
> not rely on read_only silently ignoring them if rejection is the chosen API
> contract. Never configure wildcard CORS as a substitute for permissions. Add
> foundation and serializer tests.

Produced:

- Confirmed `djangorestframework`, `django-cors-headers` and `drf-spectacular`
  already present in `backend/requirements.txt` (UTF-16) — no changes needed.
- `procurement/api/serializers.py` — `ProtectedFieldMixin` rejecting writes to
  computed fields (`protected_field`) and unknown fields (`unsupported_field`)
  with `400`; applied to every write serializer with explicit `protected_fields`.
- `tests/api/test_foundation.py` — versioned routes, anonymous-access policy,
  JSON renderer + decimal strings, CORS middleware order and env origins
  (allowed vs disallowed, no wildcard), health JSON, admin login, OpenAPI paths.
- `tests/api/test_serializer_conventions.py` — protected/unsupported rejection,
  missing/null/blank handling, ISO date rejection, precision, input/output
  separation and decimal-string output.
- README §7 — documented the strict write contract; `COVERAGE.md` refreshed
  (396 passed).

---

## Entry 5 — Unified error contract, request IDs and structured logging

> Implement one API error contract: {"error": {"code": "...", "message": "...",
> "details": {}, "request_id": "..."}}. Use the documented mapping (400 malformed
> fields/types/precision, 404 unknown resources, 409 duplicates and forbidden
> state transitions, 422 domain rejection, 500 unexpected faults with a generic
> public message). Map existing domain exceptions deliberately. Handle known
> database conflicts after transaction rollback. Do not turn all database errors
> into the same misleading response. Generate a request ID or validate a supplied
> one; return it in X-Request-ID and error bodies; use the same ID in structured
> logs. Log real UTC timestamp, level, event, request ID, method, safe path,
> status, duration and relevant non-sensitive record IDs. Log domain rejections
> at WARNING and unexpected faults at ERROR with server-side exception
> information. Do not log full bodies, credentials, banking references, review
> keys, or sensitive query parameters. Test validation, not-found, conflict,
> domain and unexpected-error paths; verify an unexpected financial failure rolls
> back changes.

Produced:

- `procurement/api/request_log.py` — structured JSON log helper and request-ID
  generate/validate helpers.
- `procurement/api/middleware.py` — `RequestIDMiddleware` (accept/generate the
  ID, echo `X-Request-ID`, log successful requests).
- `procurement/api/errors.py` — rewritten envelope (`details`, `request_id`),
  deliberate status mapping, known-unique-constraint and sqlstate conflict
  mapping, WARNING/ERROR structured logging with exception detail for faults.
- `config/settings.py` — `RequestIDMiddleware` in `MIDDLEWARE`, `LOGGING` config.
- `tests/api/test_errors.py` — status mapping, request-ID handling, logging and
  sensitive-data exclusion, rollback, and database-conflict mapping.
- README §7 error/request-id/logging documentation.

---

## Entry 6 — Catalog endpoints and the crop/grade management contract

> Implement these endpoints through the approved contract: GET/POST
> /api/v1/farmers/, GET/PATCH /api/v1/farmers/{id}/, GET/POST /api/v1/crops/,
> GET/PATCH /api/v1/crops/{id}/, GET/POST /api/v1/price-lists/. Expose allowed
> grades through crop responses and the chosen grade management contract.
> Requirements: farmer outstanding advance cannot be written through generic
> CRUD; validate crop moisture configuration and allowed grades; price creation
> calls the M2 pricing service; price history is append-only; no unrestricted
> financial update/delete actions; duplicate crop/grade/effective-date price
> returns a controlled conflict; crop/grade configuration changes preserve
> existing snapshots; used grades cannot be destructively removed from historical
> records. Do not use unrestricted ModelViewSet defaults. Test valid
> creation/update, missing fields, unknown references, duplicate prices,
> protected fields, and historical preservation.

Produced:

- `procurement/api/serializers.py` — `CropGradeRefSerializer`, `CropSerializer`
  (`allowed_grades`), `CropWriteSerializer` (moisture-bounds + grade-code
  validation, duplicate-name `409 duplicate_crop`, atomic grade reconciliation
  that refuses to remove a used grade) and `FarmerSerializer.update` (re-validates
  the merged record; identity and `outstanding_advance` stay read-only).
- `procurement/api/views.py` — `FarmerDetailView` (GET/PATCH), `CropListCreate`
  (GET/POST) and `CropDetailView` (GET/PATCH); no ModelViewSet defaults, no
  delete routes.
- `procurement/api/errors.py` — `GradeInUse` (`409 grade_in_use`) and
  `duplicate_crop` mapping.
- `procurement/api/urls.py` — `farmers/{id}/` detail PATCH, `crops/` and
  `crops/{id}/` writes, prices renamed to `price-lists/`.
- `tests/api/test_catalog.py` — 26 tests across farmers, crops and price lists.
- README §7 — endpoint table, crop/grade management contract, append-only and
  snapshot-preservation notes; `COVERAGE.md` refreshed (438 passed).

---

## Entry 7 — Advances and the bounded farmer ledger

> Implement GET/POST /api/v1/advances/ and GET /api/v1/farmers/{id}/ledger/.
> Advance creation must call the M2 advance service. Do not update outstanding
> balances in serializers or views. Reject nonpositive amounts, excess
> precision/capacity, missing or unknown farmer, and client-supplied balance or
> calculated fields. Do not expose generic advance editing/deletion that bypasses
> balance reconciliation. Ledger responses must use the M2 ledger service,
> distinguish deliveries, corrections, advances and payouts, distinguish draft
> projections from settled recovery, return current outstanding and meaningful
> arithmetic, avoid double counting earnings or recovery, and support bounded
> history. Test persisted balance changes, rollback, distinct same-day advances,
> unknown farmer, decimal strings, and ledger reconciliation.

Produced:

- `procurement/api/serializers.py` — `AdvanceCreateSerializer` now refuses
  `outstanding_advance`/`balance` (`400 protected_field`); fixed the ledger
  delivery projection to read `crop_grade_id` / `payout_id` /
  `original_delivery_id` (previously silently dropped) and exposed
  `history_from` / `history_to`.
- `procurement/api/views.py` — `FarmerLedgerView` parses `?from=`/`?to=`,
  rejects an unparseable or inverted range (`400`), and passes the window to the
  service.
- `procurement/services/ledger.py` — `build_farmer_ledger(farmer, *, since,
  until)` bounds the returned history rows while computing all aggregate totals,
  the outstanding balance and the reconciliation over the full history.
- `procurement/api/errors.py` — `_drf_validation` now reads the `code`/`message`
  of dict-shaped field errors, so list-view date/int filter errors report
  `invalid` instead of a blanket `error`.
- `tests/api/test_advances.py`, `tests/api/test_ledger_api.py` — precision,
  capacity, missing/unknown farmer, protected balance/calculated fields, same-day
  distinct advances, rollback and decimal strings; two-week ledger identity,
  draft-vs-settled separation, corrections, bounded history and range validation.
- README §7 — advances contract and ledger (bounded history, no double counting);
  `COVERAGE.md` refreshed (450 passed).

---

## Entry 8 — Delivery preview/save/edit and nested corrections

> Implement GET/POST /api/v1/deliveries/, GET/PATCH /api/v1/deliveries/{id}/,
> POST /api/v1/deliveries/preview/ and POST /api/v1/deliveries/{id}/corrections/.
> Call the existing delivery and correction services. Preview must persist
> nothing, return the complete calculation breakdown, include the effective
> business date and identify the applied price entry and rate. Save must accept
> original inputs only, recalculate authoritatively, return the stored snapshot and
> reject forged amount, deduction, applied-price and membership fields. Editing
> must preserve M2 DRAFT consistency and reject edits to FINALISED/PAID
> deliveries. Corrections must use the URL's original-delivery identifier, resolve
> and validate persisted ownership/state through the service, not trust
> client-supplied ownership or calculated signed totals, and preserve original
> snapshots. Test malformed input, missing references, missing prices, moisture
> boundaries, preview non-persistence, preview/save price changes, capacity
> overflow, finalised edits and correction ownership.

Produced:

- `procurement/api/serializers.py` — `DeliveryCorrectionCreateSerializer` (kind,
  magnitude, reason only; the original comes from the URL; client `farmer`,
  `original_delivery`, `amount`, `correction_magnitude`, `accounting_date` and
  `payout` are refused as `400 protected_field`).
- `procurement/api/views.py` — `DeliveryCorrectionsView` calls
  `corrections.record_correction` with the path delivery id.
- `procurement/api/urls.py` — `deliveries/{id}/corrections/`.
- `tests/api/test_delivery_contract.py` — 14 tests: preview breakdown + business
  date + price entry/rate + non-persistence, malformed input, unknown references,
  missing price, moisture boundaries, authoritative recalculation on price change,
  forged breakdown/membership fields, capacity overflow, DRAFT refresh on edit,
  FINALISED/PAID edit rejection, and nested-correction ownership/state/total
  rejection.
- README §7 — deliveries/corrections contract; `COVERAGE.md` refreshed
  (464 passed).

---

## Entry 9 — Payout statements, generation, finalisation and settlement

> Implement GET/POST /api/v1/payouts/, GET /api/v1/payouts/{id}/, POST
> /api/v1/payouts/generate/, POST /api/v1/payouts/{id}/finalise/ and POST
> /api/v1/payouts/{id}/mark-paid/ (renamed from /pay/). Call the existing payout
> services and keep all business calculation there. Payout statements must show
> farmer, Mon..Sun period, included deliveries/corrections with their stored
> breakdowns, gross/recovery/net, status and timestamps. Preserve snapshot and
> immutability. Do not let clients set totals, outstanding, membership or status
> through generic CRUD. For an empty week preserve the documented no-payout stance
> and return an explicit representation such as {"payout": null, "reason":
> "NO_ELIGIBLE_DELIVERIES"}. Test normal and repeated draft generation,
> supplementary payouts, 30%-capped recovery (100.05 -> 30.01), finalise/mark-paid,
> repeated/invalid transitions as controlled conflicts, mark-paid before
> finalisation, finalised financial immutability, concurrent generation and
> finalisation via the API, and rollback after an unexpected failure.

Produced:

- `procurement/api/serializers.py` — `PayoutSerializer` is now a full statement
  (`farmer_name`, stored totals/status/timestamps and a `deliveries` list of
  frozen member snapshots rendered by `DeliveryReadSerializer`); new
  `PayoutGenerationSerializer` for the generate envelope;
  `PayoutGenerateSerializer` refuses membership/total/status fields
  (`400 protected_field`) and no longer raises on an empty week.
- `procurement/api/views.py` — `PayoutGenerateView` calls `build_weekly_payout`
  and returns `{"payout": <statement>, "reason": null}` (`201`) or
  `{"payout": null, "reason": "NO_ELIGIBLE_DELIVERIES"}` (`200`); list/detail
  prefetch members; finalise/mark-paid render the statement.
- `procurement/api/urls.py` — `payouts/{id}/pay/` renamed to
  `payouts/{id}/mark-paid/`.
- `procurement/api/errors.py` — removed the now-unused `EmptyWeek` exception and
  its `empty_week` status-mapping entry (empty weeks are a success, not a
  conflict).
- `tests/api/test_payouts.py` — rewritten: statement contents, empty-week no-op,
  idempotent repeated generation, supplementary payout, `100.05 -> 30.01`
  recovery rounding, finalise/mark-paid, repeated/out-of-order transitions,
  mark-paid before finalisation, finalised immutability (405 on generic CRUD),
  rollback on unexpected failure, and two threaded API concurrency tests.
- README §7 payouts contract; `COVERAGE.md` refreshed (473 passed).

---

## Entry 10 — Bounded pagination, whitelisted ordering and list filters

> Apply bounded pagination to every growing list, including ledger history.
> Default page size 20, maximum 100, stable ordering with an id tie-breaker.
> Support filters: prices by crop and grade; deliveries by farmer and date range;
> advances by farmer and date range; payouts by farmer, week and status; ledger by
> date range and event type. Validate filter types and date ranges. Document
> whether date filters are inclusive. Whitelist ordering fields rather than
> accepting arbitrary expressions. Do not hide an unbounded nested event list
> inside a paginated wrapper. Avoid unnecessary repeated queries via related
> loading. Test pagination boundaries, maximum size, malformed filters, reversed
> date ranges, deterministic ordering, and combined filters.

Produced:

- `procurement/api/pagination.py` — `StandardPagination` default page size **20**,
  maximum **100** (over-large requests clamped, invalid sizes fall back);
  `config/settings.py` `PAGE_SIZE=20`.
- `procurement/api/filters.py` (new) — shared `parse_int`/`parse_date_param`
  (rejects impossible dates), inclusive `date_range` (400 on an inverted range),
  `order_queryset` (whitelisted + id tie-breaker) and `order_events` (stable
  multi-pass sort with `event_type`/`id` tie-breakers).
- `procurement/api/views.py` — `OrderingMixin.apply_ordering` on every list view
  with a declared `ordering_fields` whitelist and an id-terminated
  `default_ordering`; added date-range filters to deliveries/advances/corrections
  and a `week` filter to payouts; `FarmerLedgerView` rewritten to a paginated
  **event timeline** (`_ledger_events`) with `event_type` + date filters and a
  full-history `summary`, so no unbounded list is nested in the wrapper.
- `procurement/api/serializers.py` — replaced `FarmerLedgerSerializer` with
  `LedgerSummarySerializer`, a discriminated `LedgerEventSerializer`
  (`event_type`/`id`/`date`/`amount` + nullable `delivery`/`advance`/`payout`) and
  a `LedgerPageSerializer` envelope; `LEDGER_EVENT_TYPES`.
- `tests/api/test_pagination_filters.py` (new, 13 tests) — default page size,
  max-size clamping, page walking, out-of-range page, malformed types/dates,
  reversed ranges, unknown ordering, deterministic id tie-break, reversed
  ordering, inclusive date bounds, `week`/status, crop/grade and combined filters.
- `tests/api/test_ledger_api.py` — rewritten for the page envelope + event
  timeline + `event_type` filter; `tests/api/test_advances.py` ledger key updated.
- README §7 — pagination/ordering/filter table and inclusive-date note, ledger
  event-timeline contract; `COVERAGE.md` refreshed.

---

## Entry 11 — Gated reviewer business-clock aid

> Expose the existing injectable M2 clock as a gated reviewer aid. Headers:
> `X-Test-Clock`, `X-Review-Key`. Configuration: `ALLOW_REVIEW_CLOCK` defaults to
> false; the review key comes from environment configuration. Requirements:
> accept an override only when enabled and authorised; require a valid
> timezone-aware timestamp; reject malformed timestamps and unauthorised/disabled
> attempts with documented errors; use request-local clock injection; never change
> global time or shared service state; keep audit timestamps and request logs on
> real time; return the effective business date in preview. Do not log the review
> key or complete sensitive headers. Do not introduce a production bypass. Test:
> no override; valid authorised override; disabled flag; missing/wrong key;
> malformed or timezone-naive timestamp; two simultaneous requests with different
> clocks each receiving its own business date. Document configuration using
> placeholders and explain demo-only use.

Produced:

- `config/settings.py` — `ALLOW_REVIEW_CLOCK` (bool, default `False`) and
  `REVIEW_CLOCK_KEY` (str, default empty) read from the environment via
  `environ.Env`; registered `ReviewClockMiddleware` after `RequestIDMiddleware`.
- `procurement/api/middleware.py` — `ReviewClockMiddleware`: when `X-Test-Clock`
  is present, requires the aid to be enabled and `X-Review-Key` to match the
  configured key (constant-time `secrets.compare_digest`), then parses a
  timezone-aware ISO-8601 instant and installs it with the existing
  `use_clock(FrozenClock(...))` **ContextVar** for the request only. Disabled →
  `403 review_clock_disabled`, missing/wrong key → `403 review_clock_unauthorized`,
  malformed/naive → `400 review_clock_invalid`, each logged as `request.rejected`
  without the key or header values.
- `procurement/api/errors.py` — documented the three codes in `_CODE_STATUS`.
- `procurement/api/serializers.py` — added `business_date` (effective clock date,
  resolved via `get_clock().today()`) to `DeliveryPreviewSerializer`.
- `tests/api/test_review_clock.py` (new, 11 tests) — no override; authorised
  override changes `business_date` only; disabled flag; missing and wrong key;
  malformed and timezone-naive timestamp; audit `recorded_at` stays on real time
  under an override; two concurrent requests keep independent business dates with
  no leakage; a non-ASCII key is rejected (not a crash); the key/header value is
  never logged.
- `.env.example` + README §10.1 — placeholders and demo-only rationale. `COVERAGE.md`
  refreshed.

## Entry 12 — Complete OpenAPI documentation

> Complete the OpenAPI documentation for every implemented endpoint. Expose the
> schema and interactive docs; describe input/output serializers and required
> fields; document decimal-string precision, date/week interpretation,
> pagination, filtering, ordering, permission and authentication policy, the error
> envelope and its status codes, the empty-week response and finalisation/retry
> behaviour, and the optional reviewer-clock headers. Include realistic fictional
> examples that contain no credentials. Generate and validate the schema with the
> configured tooling and resolve actionable warnings. Verify that the delivery
> preview, correction, ledger and payout action responses are documented
> accurately, and do not invent fields or examples that are inconsistent with the
> actual responses.

Produced:

- `procurement/api/schema.py` (new) — the shared OpenAPI building blocks: the
  error-envelope serializers (`ErrorDetail`/`ErrorBody`/`ErrorEnvelope`), the
  `HealthSerializer`, `ERROR_RESPONSES` (400/403/404/409/422/500) and the
  `documented()`/`ordering_parameter()` helpers, the reusable query-parameter
  objects, the optional reviewer-clock header objects, and realistic fictional
  examples (error, delivery preview, correction note, ledger page, draft/empty/
  finalised payout) that mirror the exact response fields.
- `config/settings.py` — enriched `SPECTACULAR_SETTINGS`: a description covering
  the anonymous access policy, decimal-string scales, IST dates and Mon–Sun weeks,
  pagination/ordering/filtering, the error envelope and status families, the
  empty-week payout success and one-way finalisation, and the demo-only reviewer
  clock; four named enum components via `ENUM_NAME_OVERRIDES`; endpoint tags.
- `procurement/api/views.py` — annotated every operation with
  `extend_schema`/`extend_schema_view` (tags, summary, description, request,
  merged success + error responses, parameters and examples). Converted the plain
  `health` function to a DRF `@api_view` so it appears in the schema; documented
  both `201`/`200` generate outcomes; documented `finalise`/`mark-paid` with no
  request body; removed the ineffective `@extend_schema` decorators that had been
  placed on overridden `create` methods (drf-spectacular reads the HTTP handler),
  and supplied explicit descriptions so the `OrderingMixin` docstring no longer
  leaks into list operations. Also fixed the previously missing request bodies on
  `POST /deliveries/`, `/corrections/` and `/price-lists/`.
- `procurement/api/serializers.py` — annotated `GradeOrCodeField` with
  `extend_schema_field` (a grade id or code) so the price-entry request body
  resolves instead of degrading to `string`.
- `tests/api/test_schema.py` (extended from 2 to 15 tests) — validates the schema
  against the OpenAPI 3.0 spec, asserts every documented path/method, that
  operations are grouped and labelled, that internal docstrings never leak, the
  named enum components, the error envelope, and the contracts for the delivery
  write, preview `business_date`, reviewer-clock headers, payout generation's two
  outcomes, body-less payout transitions, the ledger page and list ordering.
- README §7 — added the **OpenAPI schema** subsection and corrected the ledger
  endpoint description. `COVERAGE.md` refreshed (514 passed).

## Entry 13 — Verify the API against the acceptance cases

> Verify M3 through real DRF request/response tests against the isolated
> PostgreSQL test database, covering the acceptance cases API01–API12 (valid
> requests, missing/wrong input, unknown resources, protected-field writes,
> duplicates and finalised edits, preview immutability, pagination/filtering,
> reviewer-clock rejection, concurrent clocks, unexpected failure with a
> correlated log and rollback, mark-paid-before-finalisation, and snapshot
> preservation). Run the full M1+M2 regression, the API suite, Django system
> checks, migration drift, lint, OpenAPI validation and coverage. Update the
> README, the API rule-to-service-to-test mapping and PROMPTS.md, and report the
> commands, results, acceptance matrix, remaining defects, M3→M4 readiness and a
> set of proposed logical commits. Do not commit or push.

Produced:

- `tests/api/test_acceptance_matrix.py` (new, 13 tests, marker `m3`) — the
  API01–API12 acceptance matrix driven through the real router, serializers,
  views, middleware, M2 services and isolated PostgreSQL database. The only
  injection is a deliberate view-boundary malfunction (`monkeypatch` on
  `procurement.api.views.finalise_payout`) used to prove the API10 generic-500
  path, its `request.failed` log payload and the financial rollback.
- `procurement/api/health` was already a DRF `@api_view(["GET"])` (from Entry 12),
  so the acceptance run needed no source change there.
- Defects found and fixed while writing the matrix:
  - `procurement/api/views.py` — corrected the `DeliveryDetailView.patch`
    description: editing a delivery in a FINALISED/PAID payout is `409
    payout_state_error`, while `409 not_editable` is for editing a correction
    note ("Only procurement deliveries can be edited").
  - `procurement/api/schema.py` — corrected `CORRECTION_EXAMPLE`: the correction
    `magnitude` is a **money** value at 2 dp (`245.00`, not `10.000`), a credit
    note's `amount` is **positive** (`245.00`, not `-245.00`), and the example was
    renamed "Credit note of 245.00".
- Documentation:
  - README §6 — added the M3 marker/`tests/api` commands and the current measured
    result (**527 passed**: 325 unit+integration + 202 API, 96% whole-package);
    §7 — documented the **unauthenticated (`AllowAny`)** permission policy and
    linked the API map; §11 — rewrote the limitations for the post-M3 state and
    fixed the `requirements.txt` note (it is UTF-16 LE, not UTF-8).
  - `backend/procurement/api/README.md` (new) — the API rule-to-service-to-test
    map (operation → view → M2 service → acceptance case → focused tests), the
    cross-cutting suites, and the API01–API12 acceptance matrix.
  - `COVERAGE.md` refreshed (527 passed).
- Verification run (from `backend/`, isolated PostgreSQL): full suite **527
  passed** (325 + 202); `ruff check` clean; `manage.py check` no issues;
  `makemigrations --check --dry-run` no changes; `manage.py spectacular
  --validate` exit 0 (0 warnings / 0 errors).

## Entry 14 — Build the procurement UI over the real API (M4)

> Inspect the existing React + TypeScript + Vite frontend and the M3 API, then
> build the four principal screens (delivery entry, price history, weekly
> payouts, farmer ledger) and supporting forms (farmer, crop/grade, advance,
> correction) with a reusable delivery-detail presentation and hash navigation.
> Reuse the existing scaffold and real API, keep financial calculations
> backend-authoritative, preserve decimals as strings, add no unnecessary
> dependencies and never expose DB credentials or review keys in `VITE_*`. Run
> the lint/build baseline first (report any pre-existing failures separately),
> then verify with lint, typecheck, build and a live-API smoke. Do not deploy,
> commit or push automatically.

Baseline (before changes): `npm run lint` exit 0 and `npm run build` exit 0
(18 modules) — **no pre-existing failures**.

Produced (all under `frontend/`; no new runtime dependencies):

- Foundations — `.env.example` (`VITE_API_BASE_URL`), `src/vite-env.d.ts`,
  `src/api/types.ts` (string-typed responses/requests + `as const` enum-like
  unions), `src/api/client.ts` (fetch wrapper, `ApiError`, `toApiError`,
  demo-clock headers, `X-Request-ID`), `src/api/endpoints.ts` (every operation),
  `src/api/lookups.ts` (cached farmer/grade label maps), `src/util/decimal.ts`,
  `src/util/dates.ts` (IST), `src/util/labels.ts`.
- Hooks — `src/hooks/useHashRoute.ts` (dependency-free router),
  `src/hooks/useAsync.ts`, `src/hooks/useSubmit.ts`, `src/hooks/useLookups.ts`.
- Shared components — `AppShell` (`PageHeader`, nav), `Modal`/`Loading`/`Empty`,
  `form.tsx` (`Field`, `TextInput`, `DecimalInput`, `Select`), `Pagination`,
  `StatusBadge`, `ErrorBanner`, `DemoClockControl`, `DeliveryDetail`.
- Forms — `FarmerForm`, `CropForm`, `AdvanceForm`, `CorrectionForm`.
- Screens — `DeliveriesScreen` (entry + live `preview` + list),
  `PricesScreen`, `PayoutsScreen` (+ `PayoutDetail`), `LedgerScreen`.
- Shell — rewrote `src/App.tsx` (hash routes `#/deliveries[/:id]`, `#/prices`,
  `#/payouts[/:id]`, `#/ledger`) and `src/App.css`; kept `src/index.css` and
  `src/validation/phone.ts` (reused by `FarmerForm`). The previous phone-format
  demo form was replaced.

Decisions/assumptions:

1. No new dependency: hash routing, request state and formatting are hand-rolled
   (React 19 + `react-dom` only).
2. Money/weight/percent stay strings end-to-end; inputs are scale-validated and
   posted as strings, responses are displayed verbatim.
3. Delivery/advance/correction reads expose `farmer` and grade as ids, so lists
   resolve names/codes from cached lookups; payouts already embed `farmer_name`.
4. `DeliveryRead` fields that are non-null in the schema are treated as nullable
   because they are `null` on correction notes.
5. Timestamps are shown as received (ISO-8601 `+05:30`, not `Z`).
6. Editability is discovered from the response (a refused write surfaces `409
   payout_state_error`/`not_editable`), since a delivery carries no payout status.
7. The demo clock control is gated and opt-in; its key lives in
   memory/`sessionStorage`, never in a build-time `VITE_*` value.

Verification (from `frontend/`): `npm run lint` clean; `npm run build`
(`tsc -b && vite build`) green (43 modules, ~262 kB JS / ~7.4 kB CSS). Live-API
smoke against a local `runserver`: `GET /health/` 200, and 200s for
`/farmers/`, `/deliveries/`, `/price-lists/`, `/payouts/`, `/grades/` and
`/farmers/1/ledger/` with the expected decimal-string shapes. One real
contract bug was caught and fixed by the smoke: the deliveries list was sending
`?ordering=-recorded_at`, which is not in that endpoint's whitelist (400
`invalid`) — it now uses the server default ordering (`-accounting_date, -id`).

Contract notes recorded for reviewers: `deliveries/preview/` keys the farmer as
`farmer_id` (unlike other resources); timestamps render with a `+05:30` offset,
not `Z`; the OpenAPI `DeliveryRead` schema overstates non-nullability for
correction-note fields. Documentation: README gained §5.1 (frontend setup) and
§7a (M4 UI routes, decisions, contract notes); §11 updated for the post-M4 state.

## Entry 15 — Harden the shared typed API client and add focused tests

> Implement a shared typed API client in the existing frontend style: read
> `VITE_API_BASE_URL` from environment configuration and add a placeholder to
> `frontend/.env.example`. Provide typed operations for farmers, crops/grades,
> price history, advances, delivery preview/create/retrieve/update, corrections,
> payout list/retrieve/generate/finalise/mark-paid and the farmer ledger.
> Preserve decimals as strings, serialise dates to the API contract, handle
> pagination explicitly, parse structured validation/domain errors, preserve
> request ids, handle network errors and non-JSON responses safely, support
> request cancellation, and never auto-retry financial POSTs. Never send
> frontend-computed financial fields as authoritative input. Do not assume a
> network failure means a write did not happen — surface enough for the UI to
> reconcile before retrying. Add focused API-client tests.

Produced (`frontend/`):

- `src/api/client.ts` (rewritten) — the single network choke point. Generated or
  caller-supplied `X-Request-ID`, read back from the header/body; `ApiError` now
  also carries `method`, `path`, `isWrite`, `outcome` (`rejected`/`unknown`),
  `outcomeUnknown` and a `reconciliation` object (`safeToRetry` + guidance);
  `AbortSignal` support with a distinct `request_aborted` code; safe handling of
  network failures, non-JSON success (returns `undefined`) and non-JSON errors
  (status-derived fallback envelope); explicit `Page<T>` / `api.page()` plus
  `iteratePages`/`collectPages` crawlers that follow the absolute `next` URL and
  stop at a bounded `maxPages`; `assertWritablePayload` guard rejecting
  server-computed fields, path-aware so `amount` is still legal on `POST
  /advances/`; no retries anywhere.
- `src/api/endpoints.ts` (updated) — every function accepts `RequestOptions`
  (signal/requestId/onRequestId), lists use `api.page`, and writes run date fields
  through `toApiDate`.
- `src/util/dates.ts` (extended) — `isApiDate`, `toApiDate` (IST calendar date),
  `isApiTimestamp`.
- `src/hooks/useAsync.ts` — loader now receives an `AbortSignal`; aborted requests
  are ignored and in-flight loads are cancelled on deps change/unmount. Updated
  the screens, `useLookups` and `DeliveryDetail` to pass the signal, and
  `lookups.ts` to forward it.
- `src/components/ErrorBanner.tsx` / `DemoClockControl.tsx` — surface the
  unknown-write warning and validate the clock timestamp with `isApiTimestamp`.
- `package.json` / `vitest.config.ts` — added **Vitest** (devDependency) and
  `npm test` / `npm run test:watch`; the suite runs in a Node environment with a
  stubbed `fetch`.
- Tests — `src/api/client.test.ts`, `src/api/endpoints.test.ts`,
  `src/util/dates.test.ts` (**33 tests**): URL/query building, decimal strings,
  ISO→IST date serialisation, envelope/field-detail parsing, request-id
  precedence, pagination (single page, following `next`, `maxPages` bound),
  request cancellation (in-flight abort), the protected-field guard (incl. the
  `amount`/advances exception), and the no-retry / unknown-outcome behaviour for
  network, abort and `5xx` writes.

Decisions/assumptions:

1. A dropped request, an abort, or a `5xx` can follow a committed write, so those
   are `outcome: "unknown"` with `safeToRetry: false`; a definitive `4xx/409/422`
   is `outcome: "rejected"` (the API rolls those back) and is safe to resend after
   correction. `ErrorBanner` tells the user to re-check before retrying.
2. The client never retries — including idempotent-looking GETs — to keep the
   behaviour predictable; callers decide.
3. Vitest was added as a **dev/test-only** dependency (the app still ships only
   `react` + `react-dom`); the run is Node-only and needs no browser runner.

Verification (from `frontend/`): `npm test` → **33 passed** (3 files);
`npm run lint` clean; `npm run build` (`tsc -b && vite build`) green (43 modules,
~266 kB JS / ~7.5 kB CSS).

Contract note for reviewers: `amount` is **input** for advances but a
server-computed total elsewhere, which is why the protected-field guard is
keyed by path rather than a single global list.

Documentation: README §5.1 (frontend commands incl. `npm test`) and §7a (the
"Shared API client" guarantees and its tests).

## Entry 16 — Application shell and shared UI components

> Build the application shell and shared UI components using the existing styling
> approach and minimal dependencies: navigation between the four principal
> screens; consistent forms, tables, buttons and status badges; loading, empty,
> validation-error and server-error states; pending-action controls; accessible
> confirmation dialogs; safe decimal/money formatting; IST timestamp formatting.
> Phone-width layouts must retain all actions and financial values; labels,
> keyboard access, focus handling and error associations must work; errors must
> not be communicated through colour alone; currency formatting must not lose
> decimal precision; date-only values must not shift through timezone conversion;
> timestamps must explicitly use Asia/Kolkata. No decorative charts. Add focused
> shared-component tests.

Produced (`frontend/`):

- `src/components/Button.tsx` — one button primitive with
  `primary`/`ghost`/`warn`/`danger` variants and a `pending` state (`aria-busy`,
  decorative spinner, disabled). Adopted across screens, forms, pagination and
  dialogs so in-flight actions are consistent.
- `src/components/DataTable.tsx` — a labelled, keyboard-focusable scroll region
  (`role="region"`, `tabIndex=0`) around `table.data-table`.
- `src/components/ConfirmDialog.tsx` — an `alertdialog` with a described message,
  Escape/backdrop cancel, and a pending confirm control; now guards
  finalise/mark-paid.
- `src/components/format.tsx` — `Money`, `DateOnly`, `Timestamp`, `Quantity`.
- `src/components/Modal.tsx` — focus moved in on open, Tab trapped, Escape and
  backdrop close, focus restored to the trigger; `role`/`aria-labelledby`/
  `aria-describedby`; `Loading` is a polite live region with a spinner.
- `src/components/form.tsx` — `Field` now owns the generated ids and passes
  `inputId`/`describedBy`/`invalid` to `TextInput`, `DecimalInput` and `Select`
  through context, wiring label, `aria-describedby` and `aria-invalid`; error text
  carries a literal "Error:" marker.
- `src/util/decimal.ts` — `formatAmount`/`formatMoney` group the integer part
  (Indian grouping) from the **string** and keep the fractional part verbatim
  (no float parsing, trailing zeros preserved).
- `src/components/ErrorBanner.tsx` — textual severity label plus code/status,
  field messages and request id; keeps the unknown-write warning.
- `src/components/AppShell.tsx` — skip-to-content control (a button, because a
  hash link would collide with the hash router) and focusable main region.
- Screens/details/forms updated to use `DataTable`, `Money`, `DateOnly`,
  `Timestamp`, `Button` and `ConfirmDialog`; filter selects gained labels.
- `src/App.css` — `.table-wrap` horizontal scrolling (with `min-width: max-content`
  so columns and amounts are never squeezed), money tabular numbers, danger
  button, spinner, dialog description, skip link, focus-visible on the scroll
  region, and phone-width stacking of actions.
- `vitest.config.ts` — includes `*.test.tsx`; component tests opt into jsdom with
  a per-file pragma. Added `jsdom`, `@testing-library/react` and
  `@testing-library/user-event` as **dev-only** dependencies.
- Tests — `src/util/decimal.test.ts`, `src/components/{format,Button,form,Modal,ErrorBanner,DataTable,StatusBadge,ConfirmDialog}.test.tsx`.

Decisions/assumptions:

1. **Confirmation is only for irreversible/financial transitions.** Finalise and
   mark-paid (and future destructive actions) use `ConfirmDialog`; ordinary
   creates/edits submit directly with pending controls.
2. **Date-only vs timestamps are separate components.** `DateOnly` formats the
   literal `YYYY-MM-DD` (never converted through a timezone); `Timestamp` always
   formats in Asia/Kolkata, appends `IST`, and shows the raw instant + zone in
   its tooltip.
3. **No precision-by-formatting shortcuts.** `formatMoney` never calls `Number`;
   it splits the string and groups the integer digits.
4. **The skip link is a button**, because the router treats `#/...` as navigation.
5. **Phone width keeps everything reachable by scrolling, not hiding.** Tables
   live in a focusable scroll region rather than dropping columns or actions.

Verification (from `frontend/`): `npm test` → **77 passed** (12 files);
`npm run lint` clean; `npm run build` (`tsc -b && vite build`) green (47 modules,
~271 kB JS / ~8.9 kB CSS).

Documentation: README §7a ("Shared UI shell and components"); the frontend
decision now notes that Vitest/jsdom/testing-library are dev-only.

## Entry 17 — Delivery screen against the real API

> Implement the delivery screen against the real API: farmer/crop/grade/date/
> gross/moisture inputs with decimal strings; clear an invalid grade on crop
> change; load paginated reference data; debounce/cancel previews and never let
> a stale response win; save the original inputs only; show the authoritative
> stored result and how it differs from the preview; preserve inputs on failure;
> prevent duplicate submits; do not blindly retry; permit permitted edits while
> making settled deliveries read-only and explaining why. Add focused tests.

Produced (`frontend/`):

- `src/api/lookups.ts` — farmers and grades are loaded with `collectPages`
  (`page_size=100`, `ordering=id`), so selection UIs no longer hide records
  beyond the first API page.
- `src/util/delivery.ts` — pure validation (farmer/crop/grade/date/3-dp positive
  gross/2-dp positive moisture), grade↔crop matching, preview-vs-stored
  comparison (price, entry, deduction, net, amount, accounting date),
  `moneyDelta` in minor units with `BigInt` (display only), and
  `deliveryLockReason` (corrections immutable; FINALISED/PAID locked).
- `src/hooks/useDeliveryPreview.ts` — debounced (400 ms), abortable,
  latest-wins preview. A key derived from the body invalidates an old preview
  immediately and ignores late settlements; nothing is requested for invalid
  input, and errors are not retried until the inputs change.
- `src/components/DeliveryEntryForm.tsx` — validated form, inline preview
  errors (including missing price), authoritative stored breakdown, stored-vs-
  preview comparison and delta, pending/disabled Record control, preserved
  inputs and unknown-write warning on failure, inputs cleared only on success.
- `src/screens/DeliveriesScreen.tsx` — now composes `DeliveryEntryForm`, keeps
  the recent-deliveries list and refreshes it after a save.
- `src/components/DeliveryEditForm.tsx` — prefilled edit modal; PATCHes exactly
  `{crop_grade, delivered_on, gross_weight_kg, moisture_percent}` (farmer and
  computed fields are never sent); server errors stay in the dialog with the
  inputs intact.
- `src/components/DeliveryDetail.tsx` — fetches `GET /payouts/{id}/` when a
  payout is linked, offers Edit only when the delivery is unlocked, explains
  read-only corrections/settled statements, and shows a confirmation after a
  successful edit.
- `src/util/dates.ts` — `isApiDate` now also rejects impossible calendar dates
  (`2026-02-30`, `2026-02-29`) instead of sending them to a late `400`.
- `src/App.css` — `.stored-result` separation for the authoritative breakdown.
- Tests — `src/util/delivery.test.ts`, `src/hooks/useDeliveryPreview.test.tsx`,
  `src/components/DeliveryEntryForm.test.tsx`,
  `src/components/DeliveryEditForm.test.tsx`, `src/api/lookups.test.ts`.

Decisions/assumptions:

1. **Save the original inputs, never the preview.** The preview is a hint; the
   POST body is always the six user inputs and the stored response is what the
   UI presents as truth.
2. **A preview failure is inline, not a write warning.** `POST /deliveries/preview/`
   has no side effects, so `price_not_found`/`moisture_exceeds_maximum`/
   `future_delivery_date` are shown as preview guidance rather than the shared
   unknown-outcome write banner.
3. **Latest-wins by key.** The debounce is cancelled on change; each run has its
   own `AbortController`; a response is accepted only if its key still matches,
   so a slow old preview cannot overwrite a newer one.
4. **Show what actually changed.** The stored response is compared with the
   preview snapshot captured at submit time; the price delta is computed from
   decimal strings in minor units, never through floats.
5. **Read-only is explained before it is enforced.** Settlement status comes
   from the linked payout; the edit control is hidden for corrections and
   finalised/paid payouts with a reason, while the API remains the final
   authority (a race shows its `409`).
6. **Reference data is walked, not truncated.** All pages are fetched so the
   selects are complete; the list endpoint's own pagination remains explicit.

Verification (from `frontend/`): `npm test` → **107 passed** (17 files);
`npm run lint` clean; `npm run build` (`tsc -b && vite build`) green (51
modules, ~282 kB JS / ~9.0 kB CSS). Live smoke against the real API (temporary
delivery, removed afterwards): preview `applied_price=25.75`,
`net_kg=100.00000`, `amount=2575.00`; create succeeded; PATCH
`gross_weight_kg=120.500` returned `net_kg=120.50000`, `amount=3102.88`.

Documentation: README §3 (test stack), §7a ("Delivery screen" plus decisions 6
and 8), §11; `PROMPTS.md` Entry 17.


## Entry 18 — Price-history screen against the real API

> Implement the price-history screen against the real API: crop/grade selection,
> effective-dated history with pagination and stable ordering, an add-price form
> that accepts back-dated, current and future effective dates, exact decimal
> rates, and no edit/delete because history is append-only. Explain that
> existing deliveries keep their saved price/breakdown; handle duplicate
> effective-date conflicts, missing/invalid fields, excess precision, empty
> history and loading/network errors; refresh after a successful add while
> preserving filter context. Add focused tests.

Produced (`frontend/`):

- `src/util/pricing.ts` — pure helpers: `validatePriceEntry` (crop/grade/date
  required, 2-dp positive rate via the string validator), `classifyEffectiveDate`
  + `effectiveDateNote` (back-dated/current/future), `priceConflict`
  (`409 price_already_exists` → date field, `422 grade_not_allowed` → grade
  field, otherwise `null`), `cropOptionsFromGrades`/`gradeOptionsFromGrades`, and
  `PRICE_ORDERING = "-effective_from"`.
- `src/components/PriceEntryForm.tsx` — append-only add form: crop/grade/rate/
  effective-from, posts exactly `{crop, grade, price_per_kg, effective_from}`,
  keeps crop/grade/date after success (clears only the rate), field-level errors
  for duplicate date and unallowed grade, pending/disabled submit, and no
  edit/delete control.
- `src/screens/PricesScreen.tsx` — loads every grade page via `loadGradeMap`,
  lists prices with `crop`/`crop_grade` filters and `ordering=-effective_from`,
  resets to page 1 on filter change, clears a stale grade, explains append-only
  history and price-at-recording-time, shows empty/loading/`ErrorBanner` states,
  and refetches after a save without dropping the active filter.
- `src/App.css` — small spacing additions for the banner, help text and form.
- Tests — `src/util/pricing.test.ts`, `src/components/PriceEntryForm.test.tsx`,
  `src/screens/PricesScreen.test.tsx`.

Decisions/assumptions:

1. **Append-only is reflected in the UI.** No edit or delete control is rendered:
   the API exposes neither, and a wrong price is corrected by appending an entry
   with a different effective date. The screen says so rather than implying the
   history can be mutated.
2. **Explain price-at-recording-time.** A price change never re-prices existing
   deliveries; the delivery stores its resolved price and breakdown, so the
   screen tells the user that earlier deliveries keep the saved figures.
3. **Validate locally, let the server own uniqueness.** The rate is checked for
   scale/positivity before submit; duplicate dates and grade/crop mismatches are
   mapped from the API's `409`/`422` onto the date/grade fields, with the inputs
   preserved so the user can adjust rather than re-enter.
4. **Stable, explicit ordering.** The list always sends
   `ordering=-effective_from`; the API's id tie-breaker makes equal dates
   deterministic across pages.
5. **Preserve context after a save.** The history refreshes (page 1) while
   keeping the current crop/grade filters; the success notice offers a shortcut
   to reveal the new entry, clearing filters only if it would otherwise be
   hidden.

Verification (from `frontend/`): `npm test` → **131 passed** (20 files);
`npm run lint` clean; `npm run build` (`tsc -b && vite build`) green (53
modules, ~285 kB JS / ~9.1 kB CSS). Live smoke against the real API:
`POST /price-lists/` with an existing `(grade 1, 2026-04-01)` → `409
price_already_exists`; a new future entry `2026-12-31` → `201` (id 11), then
deleted via `manage.py shell` (grade 1 back to 3 entries).

Documentation: README §7a ("Price history screen" plus decision 9), §11;
`PROMPTS.md` Entry 18.

## Entry 19 — Weekly payout selection and statements against the real API

> Implement weekly payout selection and statements: choose a farmer and a
> business week, show the Monday–Sunday bounds from the API's normalisation
> contract, generate/refresh a Draft through the API, and display the included
> deliveries and signed correction notes with links to the original delivery
> details and stored breakdowns. Show gross, the estimated Draft
> recovery/net (not yet applied), the finalised recovery/net and the
> status/timestamps; keep every financial field read-only and explain that a
> Draft has not reduced the outstanding advance. Confirm before finalisation and
> show the saved Final statement plus refreshed balance data; allow Mark Paid
> only for a Finalised statement. Never recover advances in frontend code. Handle
> duplicate clicks, conflicting/stale state, failed finalisation without losing
> context, ambiguous network results (re-fetch before retrying), supplementary
> payouts, and zero/negative statements. Add focused tests.

Produced (`frontend/`):

- `src/util/payout.ts` — pure helpers: `DRAFT_ADVANCE_NOTE`, `isNonPositiveMoney`
  (string-only), `payoutActions` (Draft → finalise, Finalised → mark paid, Paid →
  read-only), `sameWeekStatements` + `isSupplementary`, `classifyGeneration`
  (`payout` vs `NO_ELIGIBLE_DELIVERIES`), `generateEmptyMessage`,
  `isPayoutStateConflict`, `finaliseConfirmation`/`markPaidConfirmation` and
  `nonPositiveNote`.
- `src/components/PayoutGenerateForm.tsx` — farmer + "any day" picker; previews
  the normalised Monday–Sunday week, posts the chosen date as `week_start`, shows
  the empty-week success without inventing a payout, maps a settled-week `409`
  to an explanation plus `onChanged`, re-checks the week after an ambiguous
  network result (never auto-retries), and blocks a second in-flight submit.
- `src/components/PayoutStatement.tsx` — read-only statement: stored totals,
  Draft labels ("Estimated draft recovery", "Not yet applied", "Estimated draft
  net"), finalised/paid totals ("Advance recovered", "Net payable"), statement
  lines with stored breakdowns and original-delivery links, supplementary banner,
  confirmation summary (farmer/week/gross/draft net/outstanding + server policy),
  Finalise/Mark paid with double-click guards, ambiguous-write reconciliation via
  `GET /payouts/{id}/`, stale `409` handling, and a read-only Paid state.
- `src/screens/PayoutsScreen.tsx` — list with farmer/status filters, newest-week
  ordering and pagination; a local `usePayoutDetail` hook loads the statement,
  same-week siblings and `GET /farmers/{id}/` together, keeps the last settled
  view mounted during a reload, and starts clean on a new statement id.
- `src/App.css` — `.statement-totals`, `.stat-note`, `.confirm-summary` and
  `.week-preview`.
- `vitest.config.ts` — `testTimeout: 30000` (the expanded 23-file jsdom suite
  exceeded the 5 s default under parallel workers).
- Tests — `src/util/payout.test.ts`, `src/components/PayoutGenerateForm.test.tsx`,
  `src/components/PayoutStatement.test.tsx`.

Decisions/assumptions:

1. **The server owns the week and the money.** The form previews
   `mondayOf`/`sundayOf` but sends the picked day; the API normalises it. All
   totals come from the response, and the UI never computes advance recovery.
2. **Draft totals are shown as stored, labelled as estimates.** The API stores
   Draft `advance_deduction = 0.00` and `net_amount = gross_amount`; the screen
   says recovery is not yet applied instead of predicting `min(outstanding, 30%)`.
3. **No optimistic transitions.** Finalise/Mark paid render the server's returned
   statement immediately, then re-fetch it with the farmer's balance. A network
   failure triggers a read before any retry; nothing is resent automatically.
4. **Conflicts preserve context.** A `409 payout_state_error` closes the
   confirmation, shows the server message and refreshes the statement/list rather
   than leaving a stale dialog. Failed finalisation keeps the statement and
   dialog so the user can decide.
5. **Supplementary statements stay visible.** The detail load also lists the
   same farmer/week, so a later Draft is labelled "Supplementary payout" and the
   earlier statement is linked.
6. **Settled statements are read-only.** Paid statements render a "Settled —
   read-only" note and no action; corrections are linked, never edited.

Verification (from `frontend/`): `npm test` → **154 passed** (23 files);
`npm run lint` clean; `npm run build` (`tsc -b && vite build`) green (56
modules, ~296 kB JS / ~9.4 kB CSS). Live smoke against the real API:
`GET /payouts/` → `200` with `count: 0`; `POST /payouts/generate/`
(`farmer: 1`, `week_start: 2026-10-14`) → `200
{"payout":null,"reason":"NO_ELIGIBLE_DELIVERIES"}` (no data created; port 8000
released).

Documentation: README §7a ("Weekly payouts screen" plus decisions 10–11), §11;
`PROMPTS.md` Entry 19.

## Entry 20 — Farmer ledger screen against the real API

> Implement the farmer-ledger screen against the real ledger API: farmer
> details, authoritative outstanding advance and reconciliation values, the
> advance/delivery/correction/payout history with payout and payment states,
> inclusive date/type filters and bounded pagination. Link to payout statements
> and original deliveries without losing farmer context, never derive an
> all-time balance from one page, never double count a delivery and its payout,
> and clearly separate Draft projections from finalised recoveries. Add focused
> tests for pagination, filtering, empty history, errors, signed corrections and
> the displayed balance after financial actions.

Produced (`frontend/`):

- `src/util/ledger.ts` — pure copy/formatting helpers: ledger tones, event
  titles and amount meanings, Draft versus settled recovery notes, delivery
  assignment labels, payout arithmetic warnings, the no-double-counting and
  once-only recovery copy, the earnings identity string, empty-window copy,
  `LEDGER_PAGE_SIZE`, and context link/back helpers.
- `src/screens/LedgerScreen.tsx` — rewritten read-only ledger: farmer selector
  with deep-linkable `?farmer=`, farmer name/phone/village/bank plus the stored
  outstanding advance, full-account totals and reconciliation, history window,
  inclusive `from`/`to` and event-type filters (each resets to page 1), bounded
  20-row pagination, signed correction rows, payout status/timestamps, links to
  deliveries/payouts with `from=ledger&farmer=<id>`, a Refresh action and
  distinct empty/error states.
- `src/hooks/useHashRoute.ts` — parses an optional query string into
  `route.params`; adds `replaceHash` for context-only URL updates that notify the
  router without adding a history entry.
- `src/App.tsx` — passes the deep-linked farmer to the ledger, returns from a
  delivery/payout detail to that farmer's ledger when the context is present, and
  keeps direct links unchanged.
- `src/components/DeliveryDetail.tsx` — preserves the ledger context on its
  original-delivery and payout links.
- `src/screens/PayoutsScreen.tsx` — preserves the context from a payout
  statement to its member deliveries and supplementary statements.
- Tests — `src/util/ledger.test.ts`, `src/screens/LedgerScreen.test.tsx`.

Decisions/assumptions:

1. **The API summary is the balance.** `outstanding_advance`, all totals and the
   reconciliation are rendered from the ledger response's full-history summary.
   The event table is only a bounded/filterable window, and the screen states
   that paging cannot change the balance.
2. **Draft money is not settled money.** Draft payouts stay in
   `draft_projection`, are labelled as projections and never reduce the
   outstanding advance in the UI; no `min(outstanding, 30%)` recovery is
   calculated in the browser.
3. **No double counting is explained, not recomputed.** The screen renders the
   API's settled/draft/unassigned/recorded values and identity flag, and explains
   that a payout's members are not added again and that recovery happens once at
   finalisation.
4. **Context travels in the hash.** Detail links carry
   `?from=ledger&farmer=<id>`; Back returns to the same farmer's ledger and the
   delivery detail keeps the context on further links. Direct links without the
   context behave as before.
5. **Refresh, not optimistic mutation.** The ledger is read-only, so after a
   finalise/mark-paid elsewhere the user refreshes to re-read the authoritative
   summary and timeline.

Verification (from `frontend/`): `npm test` → **169 passed** (25 files);
`npm run lint` clean; `npm run build` (`tsc -b && vite build`) green (57
modules, ~304 kB JS / ~9.4 kB CSS). Live smoke against the real API:
`GET /farmers/1/ledger/` → `200` (count 0; farmer Aarti Bhosale; outstanding
`0.00`; reconciled true; stored/expected/difference `0.00`; identity holds);
`GET /farmers/1/advance-reconciliation/` → `200` (all totals `0.00`,
reconciled true). No data created; port 8000 released.

Documentation: README §7a ("Farmer ledger screen" plus decisions 12–15), §11;
`PROMPTS.md` Entry 20.
