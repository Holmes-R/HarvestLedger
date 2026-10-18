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
