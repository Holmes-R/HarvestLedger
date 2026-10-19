# M3 HTTP API (`procurement.api`)

The API is a **thin adapter** over `procurement.services`. Serializers validate
request *shape* (types, required fields, decimal precision, reference ids); the
views resolve ids, call the M2 service and translate the result into an HTTP
response. No business rule is re-implemented here — money, pricing, deductions,
scheduling, recovery and corrections all live in `procurement/services`.

Mounted under `/api/v1/` (`config/urls.py`). Interactive docs at `/api/docs/`;
raw schema at `/api/schema/`.

## Authentication and permissions

Every endpoint is `AllowAny` and there is **no authentication** (no token,
session or user model). This is a deliberate, documented scope decision: the
assignment specifies no identity or access control, so write safety comes from
the strict write contract (`ProtectedFieldMixin` refuses server-computed fields)
rather than from a caller identity. The only keyed surface is the demo-only
reviewer-clock aid (`ALLOW_REVIEW_CLOCK` / `REVIEW_CLOCK_KEY`, off by default).

See the root [`README.md`](../../../README.md) §7 for pagination, ordering,
filters, the error envelope and the status map.

## Operation -> service -> test map

Every operation, the M2 service (or read model) it delegates to, and where it is
pinned by tests. "APIxx" refers to the acceptance matrix below.

| Method | Endpoint (name) | M2 service / owner | Acceptance | Focused tests |
| --- | --- | --- | --- | --- |
| GET | `/health/` (`api:health`) | — (liveness) | API01 | `test_reference.py::test_health`, `test_foundation.py::test_health_returns_json` |
| GET/POST | `/farmers/` (`api:farmer-list`) | ORM + Indian-mobile validation | API01, API02, API04 | `test_reference.py`, `test_catalog.py`, `test_serializer_conventions.py` |
| GET/PATCH | `/farmers/{id}/` (`api:farmer-detail`) | ORM; `outstanding_advance` refused | API01, API03, API04 | `test_catalog.py::test_farmer_patch_*` |
| GET | `/farmers/{id}/ledger/` (`api:farmer-ledger`) | `ledger.build_farmer_ledger` | API01, API03 | `test_ledger_api.py` |
| GET | `/farmers/{id}/advance-reconciliation/` (`api:advance-reconciliation`) | `advances.assert_outstanding_reconciles` | API01, API03 | `test_advances.py::test_reconciliation_*` |
| GET/POST | `/crops/` (`api:crop-list`) | ORM + moisture-bounds / grade-set rules | API01, API02, API12 | `test_catalog.py::test_crop_create_*` |
| GET/PATCH | `/crops/{id}/` (`api:crop-detail`) | ORM; grade history preserved | API01, API03, API12 | `test_catalog.py::test_crop_patch_*` |
| GET | `/grades/` (`api:grade-list`) | ORM (`crop` filter) | API01 | `test_reference.py::test_grades_filter_by_crop` |
| GET/POST | `/price-lists/` (`api:price-list`) | `pricing.create_price_entry` (resolve in serializer) | API01, API02, API03, API05, API12 | `test_reference.py::test_price_*`, `test_catalog.py::test_price_*` |
| POST | `/deliveries/preview/` (`api:delivery-preview`) | `delivery.preview_delivery` (writes nothing) | API01, API02, API06, API08, API09 | `test_delivery_contract.py::test_preview_*`, `test_review_clock.py` |
| GET/POST | `/deliveries/` (`api:delivery-list`) | `delivery.record_delivery` | API01, API02, API03, API04, API07 | `test_deliveries.py`, `test_delivery_contract.py::test_save_*` |
| GET/PATCH | `/deliveries/{id}/` (`api:delivery-detail`) | `delivery.edit_delivery` | API01, API05 | `test_deliveries.py::test_edit_*`, `test_delivery_contract.py::test_edit_*` |
| POST | `/deliveries/{id}/corrections/` (`api:delivery-corrections`) | `corrections.record_correction` (URL original) | API01, API03 | `test_delivery_contract.py::test_nested_correction_*` |
| GET/POST | `/corrections/` (`api:correction-list`) | `corrections.record_correction` | API01, API03, API04 | `test_corrections.py` |
| GET | `/corrections/{id}/` (`api:correction-detail`) | ORM read | API01, API03 | `test_corrections.py::test_correction_list_and_detail` |
| GET/POST | `/advances/` (`api:advance-list`) | `advances.post_advance` | API01, API02, API03, API04 | `test_advances.py` |
| GET | `/advances/{id}/` (`api:advance-detail`) | ORM read (append-only; no PATCH/DELETE) | API01, API03 | `test_advances.py::test_advance_*` |
| POST | `/payouts/generate/` (`api:payout-generate`) | `payouts.build_weekly_payout` (empty week -> `200` null) | API01, API04 | `test_payouts.py::test_generate_*` |
| GET | `/payouts/` (`api:payout-list`) | ORM read (statement) | API01, API04, API07 | `test_payouts.py::test_payout_list_filters` |
| GET | `/payouts/{id}/` (`api:payout-detail`) | ORM read (`_refresh_totals` view) | API01, API04 | `test_payouts.py::test_payout_detail_includes_members` |
| POST | `/payouts/{id}/finalise/` (`api:payout-finalise`) | `payouts.finalise_payout` | API01, API10 | `test_payouts.py::test_finalise_*` |
| POST | `/payouts/{id}/mark-paid/` (`api:payout-mark-paid`) | `payouts.mark_payout_paid` | API01, API11 | `test_payouts.py::test_mark_paid_*` |

Cross-cutting pieces are pinned by their own suites:

| Concern | Module | Tests |
| --- | --- | --- |
| Error envelope, status map, DB-conflict mapping, logging | `api/errors.py`, `api/request_log.py` | `test_errors.py` |
| Bounded pagination, ordering, filters | `api/pagination.py`, `api/filters.py` | `test_pagination_filters.py` |
| Request id + reviewer-clock middleware | `api/middleware.py` | `test_review_clock.py` |
| OpenAPI schema / Swagger UI | `api/schema.py`, `config/settings.py` | `test_schema.py` |
| Versioning, anonymous policy, CORS, renderers | `config/settings.py`, `config/urls.py` | `test_foundation.py` |
| Strict write contract (protected/unsupported fields) | `api/serializers.py` | `test_serializer_conventions.py`, `test_delivery_contract.py` |

## API01-API12 acceptance matrix

`tests/api/test_acceptance_matrix.py` encodes the twelve assignment acceptance
cases one-to-one as real DRF request/response traffic through the router,
serializers, views, middleware, M2 services and the isolated PostgreSQL test
database. M2 behaviour is never mocked; the only injection is a deliberate
view-boundary malfunction for API10.

| Case | Requirement | Test |
| --- | --- | --- |
| API01 | Valid requests for every core endpoint (status + response + persisted) | `test_api01_valid_requests_for_every_core_endpoint`, `test_api01_read_only_routes_reject_mutations` |
| API02 | Missing fields / wrong types -> consistent errors, no partial writes | `test_api02_missing_fields_and_wrong_types_leave_no_partial_writes` |
| API03 | Unknown resources -> documented not-found codes | `test_api03_unknown_resources_are_documented_not_found` |
| API04 | Protected writes (amount, applied rate, balance, membership, status) refused | `test_api04_protected_field_writes_are_rejected` |
| API05 | Duplicate prices and finalised edits -> `409` + stable codes | `test_api05_duplicate_prices_and_finalised_edits_are_conflicts` |
| API06 | Preview mutates no Delivery, Payout, Advance or balance | `test_api06_preview_mutates_nothing` |
| API07 | Bounded, deterministic pagination/filtering + controlled invalid errors | `test_api07_pagination_filtering_and_invalid_errors` |
| API08 | Reviewer clock: valid / disabled / malformed / wrong key | `test_api08_reviewer_clock_valid_and_rejected_scenarios` |
| API09 | Concurrent clocks do not leak across requests | `test_api09_concurrent_clocks_do_not_leak` |
| API10 | Unexpected failure -> generic `500`, correlated log, financial rollback | `test_api10_unexpected_failure_500_correlated_log_and_rollback` |
| API11 | Mark-paid before finalisation -> `409`, no financial/state change | `test_api11_mark_paid_before_finalisation_is_conflict_without_changes` |
| API12 | Crop/grade changes preserve historical delivery snapshots | `test_api12_crop_and_grade_changes_preserve_delivery_snapshots` |

Run the matrix and the whole API suite from `backend/`:

```bash
venv/Scripts/python.exe -m pytest tests/api/test_acceptance_matrix.py
venv/Scripts/python.exe -m pytest tests/api -m m3
```
