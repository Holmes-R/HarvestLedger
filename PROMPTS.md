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

