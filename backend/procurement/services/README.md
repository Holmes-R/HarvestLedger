# M2 service layer (`procurement.services`)

Business rules for the procurement/payout engine live here, one concern per
module, so that calculations stay separate from ORM/HTTP orchestration. Views,
serializers and signals must call these functions rather than re-implementing
rules.

Financial writes run inside `transaction.atomic()` and take row locks via
`select_for_update()` in a fixed order: **farmer -> payout -> deliveries (by
pk)**. There are no process-local locks and no HTTP clock headers.

## Domain exceptions and stable error codes

All domain (business-rule) errors derive from `ServiceError` and carry a stable
`.code` (plus `.message`) for programmatic handling:

| Exception (`procurement.services.errors`) | `.code`                  | Raised when |
| --- | --- | --- |
| `ServiceError` | `service_error` | base class; code overridable per instance |
| `PriceNotFound` | `price_not_found` | no price entry is effective on/before the date |
| `GradeNotAllowed` | `grade_not_allowed` | grade does not exist for the crop (disallowed grade) |
| `PriceAlreadyExists` | `price_already_exists` | `(grade, effective_from)` is already priced |
| `AdvanceReconciliationError` | `advance_reconciliation_failed` | advances/recoveries disagree with the stored balance |
| `MoistureExceedsMaximum` | `moisture_exceeds_maximum` | delivery moisture `>` crop `max_moisture` |
| `PayoutStateError` | `payout_state_error` | a payout operation is attempted from an invalid state |

Each module re-exports the errors it raises
(e.g. `delivery.MoistureExceedsMaximum`, `pricing.PriceNotFound`,
`payouts.PayoutStateError`).

Input/field validation uses Django's `ValidationError` with an explicit
`code=`, kept separate from the domain exceptions above. Codes in use:
`invalid_kind`, `not_positive`, `reason_required`, `original_not_settled`,
`invalid_moisture_bounds`, `not_finite`, `too_precise`, `too_many_digits`
(see `validation.py` / `precision.py`).

## Business clock (injection)

`procurement.clock`:

- `Clock` protocol: `now()` -> aware UTC instant, `today()` -> IST business date.
- `SystemClock` (default) and `FrozenClock(instant)` (tests).
- `business_date(instant, tz=BUSINESS_TIMEZONE)` -> IST `date`; rejects naive
  instants. `Asia/Kolkata` is UTC+05:30, so **18:30 UTC is the next IST day**.
- `week_start` / `week_end` / `week_bounds(date)` -> Monday..Sunday inclusive.
- `business_week_bounds(instant)` -> IST Monday..Sunday week for an instant.

Services take an explicit `clock: Clock | None = None` argument and fall back to
`get_clock()`. `use_clock(clock)` installs a **context-local** override (backed
by `contextvars.ContextVar`, so no process-global mutation and safe under threads
/ async); it is restored on exit. Audit timestamps
(`created_at`/`recorded_at`/`finalised_at`/`paid_at`) always use real aware
instants from `django.utils.timezone.now()` -- never the business clock.

## Service interfaces

### `procurement.services.delivery`

- `calculate_breakdown(gross_weight_kg, moisture_percent, price_per_kg, threshold, max_moisture) -> Breakdown`
  - Pure function (no DB). `Breakdown` is a frozen dataclass with
    `deduction_percent` (2dp), `deduction_kg` / `net_kg` (5dp), `amount` (2dp).
  - Raises `ValidationError` for non-positive / over-precise inputs and invalid
    moisture bounds; raises `MoistureExceedsMaximum` above `max_moisture`.
- `preview_delivery(*, farmer, crop_grade, delivered_on, gross_weight_kg, moisture_percent, clock=None) -> DeliveryPreview`
  - Validates inputs, rejects a future `delivered_on` against the injected clock
    (`future_delivery_date`), resolves the price and returns the full breakdown.
    **Persists nothing.**
- `record_delivery(*, farmer, crop_grade, delivered_on, gross_weight_kg, moisture_percent, clock=None) -> Delivery`
  - Re-validates and re-calculates authoritatively (never trusts a preview),
    freezes the snapshot (`threshold_used`, breakdown, `applied_price`,
    `price_list_entry` FK) and writes atomically under the farmer lock;
    `accounting_date == delivered_on` for `PROCUREMENT`.
- `edit_delivery(delivery, *, delivered_on=None, crop_grade=None, gross_weight_kg=None, moisture_percent=None, clock=None) -> Delivery`
  - Recalculates an existing `PROCUREMENT` delivery. Raises `PayoutStateError`
    for a delivery in a FINALISED/PAID payout. The frozen price is preserved
    unless `crop_grade`/`delivered_on` changes. If the delivery belongs to a
    DRAFT payout the draft totals are refreshed; a week change moves the delivery
    to the correct DRAFT (created if needed) and removes an emptied old draft.

### `procurement.services.pricing`

- `resolve_price(crop_grade, on_date) -> PriceListEntry`
  - Latest entry with `effective_from <= on_date` (exact date included; future
    entries excluded); raises `PriceNotFound` naming the crop and grade.
- `create_price_entry(crop, grade, price_per_kg, effective_from) -> PriceListEntry`
  - Append-only: adds a new immutable entry; back-dated dates are allowed and
    never rewrite existing entries/snapshots. `grade` is a `CropGrade` (must
    belong to `crop`) or a grade code (must exist under `crop`); otherwise raises
    `GradeNotAllowed`. Rejects over-precise/non-positive rates with
    `ValidationError`, and a duplicate `(grade, effective_from)` -- whether
    caught up front or by the DB unique constraint -- with `PriceAlreadyExists`.
  - There is intentionally **no update/delete** service function.

### `procurement.services.advances`

- `post_advance(farmer, amount, given_on) -> Advance`
  - Validates a saved farmer and a positive, in-precision `Decimal` amount;
    locks the farmer inside `transaction.atomic()` and increases
    `outstanding_advance` exactly once. Same-day advances are separate records
    (`(farmer, given_on)` is not a dedup key). Recovery is **not** done here.
- `reconcile_outstanding(farmer) -> AdvanceReconciliation` / `assert_outstanding_reconciles(farmer)`
  - Read-only check that `sum(advances) - sum(advance_deduction on FINALISED/PAID
    payouts)` equals the stored balance; each payout counts once (`PAID` is a
    later state of the same payout, not a second recovery). Reports drift via
    `AdvanceReconciliationError` and never repairs the balance.

### `procurement.services.payouts`

- `build_weekly_payout(farmer, week_start) -> Payout | None`
  - Normalises `week_start` to that week's Monday (`week_bounds`) and selects the
    farmer's unassigned records by `accounting_date` in `[Mon, Sun]`, using their
    **stored** `amount` (no re-pricing). At most one DRAFT per farmer/week;
    repeated calls reuse it (no duplicates); membership changes and the recomputed
    DRAFT totals happen together under the farmer lock. Returns `None` for an
    empty week; raises `PayoutStateError` when the week is settled with nothing
    new to add. A late record after finalisation yields a supplementary DRAFT.
    Generating/refreshing a DRAFT never changes `outstanding_advance`.
- `finalise_payout(payout) -> Payout`
  - DRAFT -> FINALISED exactly once; applies advance recovery
    (`min(outstanding, round(0.30 * gross, 2))`); raises `PayoutStateError` if
    not DRAFT.

### `procurement.services.corrections`

- `record_correction(original_delivery, kind, magnitude, reason, *, clock=None) -> Delivery`
  - CREDIT_NOTE (+) / DEBIT_NOTE (-) against a FINALISED/PAID original; inherits
    the farmer, never mutates the original, stamps `accounting_date` with the
    injected/`get_clock()` IST business date.

### Helpers

- `procurement.services.money`: `quantize_money`, `advance_recovery_cap`,
  `advance_recovery`, `ADVANCE_RECOVERY_RATE = Decimal("0.30")`.
- `procurement.services.locking`: `lock_farmer`, `lock_payout`, `lock_deliveries`.
- `procurement.services.validation`: `as_decimal`.

## M2 test -> service map

| Test (marker `m2`) | Intended service |
| --- | --- |
| `tests/unit/test_delivery_math.py::test_moisture_at_threshold_has_no_deduction` | `delivery.calculate_breakdown` |
| `...::test_threshold_plus_0_99_still_floors_to_zero` | `delivery.calculate_breakdown` |
| `...::test_full_point_flooring` | `delivery.calculate_breakdown` |
| `...::test_exact_moisture_boundaries` (x3) | `delivery.calculate_breakdown` |
| `...::test_moisture_above_maximum_is_rejected` | `delivery.calculate_breakdown` (`MoistureExceedsMaximum`) |
| `...::test_deduction_is_capped_at_ten_percent` | `delivery.calculate_breakdown` |
| `...::test_nonpositive_ordinary_inputs_are_rejected` (x4) | `delivery.calculate_breakdown` (`ValidationError`) |
| `...::test_overprecise_inputs_are_rejected` (x2) | `delivery.calculate_breakdown` / `validation.as_decimal` |
| `...::test_monetary_rounding_is_half_up` | `delivery.calculate_breakdown` / `money.quantize_money` |
| `...::test_fractional_arithmetic_keeps_decimal_and_documented_scales` | `delivery.calculate_breakdown` |
| `...::test_gross_equals_deduction_plus_net` (x3) | `delivery.calculate_breakdown` |
| `tests/unit/test_money.py::test_recovers_thirty_percent_when_outstanding_is_larger` | `money.advance_recovery` |
| `...::test_recovers_only_the_remaining_outstanding_balance` | `money.advance_recovery` |
| `...::test_cap_rounds_an_exact_half_cent_up` | `money.advance_recovery_cap` |
| `...::test_no_recovery_without_outstanding` | `money.advance_recovery` |
| `...::test_no_recovery_on_zero_or_negative_gross` (x2) | `money.advance_recovery` |
| `tests/integration/test_prices.py::test_exact_effective_date_wins` | `pricing.resolve_price` |
| `...::test_latest_eligible_price_is_used` | `pricing.resolve_price` |
| `...::test_multiple_historical_entries_pick_the_latest_eligible` | `pricing.resolve_price` |
| `...::test_missing_crop_grade_combination_raises` | `pricing.resolve_price` (`PriceNotFound`) |
| `...::test_date_before_earliest_price_is_not_eligible` | `pricing.resolve_price` (`PriceNotFound`) |
| `...::test_future_only_price_is_not_eligible` | `pricing.resolve_price` |
| `...::test_missing_price_error_names_crop_and_grade` | `pricing.resolve_price` (`PriceNotFound`) |
| `...::test_historical_snapshot_survives_a_later_backdated_price` | `pricing.resolve_price` + `delivery.record_delivery` |
| `...::test_create_price_entry_appends_history` | `pricing.create_price_entry` |
| `...::test_create_price_entry_accepts_a_grade_instance` | `pricing.create_price_entry` |
| `...::test_create_price_entry_rejects_invalid_rates` | `pricing.create_price_entry` (`ValidationError`) |
| `...::test_create_price_entry_rejects_disallowed_grade_code` | `pricing.create_price_entry` (`GradeNotAllowed`) |
| `...::test_create_price_entry_rejects_invalid_crop_grade_relationship` | `pricing.create_price_entry` (`GradeNotAllowed`) |
| `...::test_duplicate_effective_date_is_rejected` | `pricing.create_price_entry` (`PriceAlreadyExists`) |
| `...::test_database_uniqueness_conflict_reports_price_already_exists` | `pricing.create_price_entry` (`PriceAlreadyExists`) |
| `...::test_backdated_price_insertion_does_not_rewrite_existing_entries` | `pricing.create_price_entry` + `resolve_price` |
| `tests/integration/test_delivery_service.py::test_missing_price_writes_nothing` | `delivery.record_delivery` (`PriceNotFound`) |
| `...::test_freezes_threshold_price_and_breakdown` | `delivery.record_delivery` |
| `...::test_moisture_over_max_writes_nothing` | `delivery.record_delivery` (`MoistureExceedsMaximum`) |
| `...::test_preview_returns_full_breakdown_and_persists_nothing` | `delivery.preview_delivery` |
| `...::test_preview_matches_the_saved_snapshot` | `delivery.preview_delivery` + `record_delivery` |
| `...::test_record_re_resolves_price_and_ignores_the_earlier_preview` | `delivery.record_delivery` (authoritative) |
| `...::test_future_delivery_date_is_rejected` | `delivery.preview_delivery` / `record_delivery` (`future_delivery_date`) |
| `...::test_delivery_on_the_business_date_is_allowed` | `delivery.record_delivery` (injected clock) |
| `...::test_preview_requires_a_saved_farmer_and_grade` | `delivery.preview_delivery` (`ValidationError`) |
| `...::test_snapshot_is_preserved_when_a_new_price_is_added` | `delivery.record_delivery` snapshot |
| `...::test_edit_refreshes_the_draft_totals` | `delivery.edit_delivery` + DRAFT refresh |
| `...::test_edit_preserves_the_frozen_price_when_a_new_price_is_added` | `delivery.edit_delivery` (frozen price) |
| `...::test_edit_to_a_new_date_re_resolves_the_price` | `delivery.edit_delivery` (basis change) |
| `...::test_edit_moves_the_delivery_to_the_new_week_draft` | `delivery.edit_delivery` + draft reassignment |
| `...::test_edit_is_rejected_for_a_settled_payout` | `delivery.edit_delivery` (`PayoutStateError`) |
| `...::test_edit_rejects_amounts_above_the_moisture_maximum` | `delivery.edit_delivery` (`MoistureExceedsMaximum`) |
| `tests/integration/test_advances.py::test_posting_accumulates_outstanding_balance` | `advances.post_advance` |
| `...::test_same_day_advances_are_separate_records` | `advances.post_advance` |
| `...::test_nonpositive_amount_is_rejected` (x2) | `advances.post_advance` (`ValidationError`) |
| `...::test_overprecise_amount_is_rejected` | `advances.post_advance` |
| `...::test_posting_requires_a_saved_farmer` | `advances.post_advance` (`farmer_required`) |
| `...::test_failure_rolls_back_the_advance_and_the_balance` | `advances.post_advance` (atomic rollback) |
| `...::test_reconciliation_holds_before_and_after_payout_recovery` | `advances.reconcile_outstanding` + `payouts.finalise_payout` |
| `...::test_paid_is_not_counted_as_a_second_recovery` | `advances.reconcile_outstanding` (PAID once) |
| `...::test_reconciliation_reports_drift_without_repairing_it` | `advances.assert_outstanding_reconciles` (`AdvanceReconciliationError`) |
| `...::test_concurrent_advances_do_not_lose_balance_updates` | `advances.post_advance` (farmer lock) |
| `tests/integration/test_payouts.py::test_monday_to_sunday_selection` | `payouts.build_weekly_payout` |
| `...::test_generation_assigns_each_delivery_once` | `payouts.build_weekly_payout` |
| `...::test_draft_payout_does_not_reduce_outstanding` | `payouts.build_weekly_payout` |
| `...::test_recovery_cap_and_outstanding_carries_across_weeks` | `payouts.finalise_payout` / `money.advance_recovery` |
| `...::test_large_outstanding_advance_carries_beyond_two_weeks` | `payouts.finalise_payout` / `money.advance_recovery` |
| `...::test_recovery_cap_rounds_an_exact_half_cent_up` | `payouts.finalise_payout` / `money.advance_recovery_cap` |
| `...::test_finalisation_changes_balance_exactly_once` | `payouts.finalise_payout` |
| `...::test_finalised_payout_is_immutable` | `payouts.finalise_payout` (`PayoutStateError`) |
| `...::test_empty_week_creates_no_payout` | `payouts.build_weekly_payout` |
| `...::test_monetary_identities` | `payouts.build_weekly_payout` / `money` |
| `...::test_supplementary_payout_allowed_after_finalisation` | `payouts.build_weekly_payout` |
| `...::test_no_advance_means_zero_deduction` | `payouts.finalise_payout` / `money.advance_recovery` |
| `...::test_week_is_normalized_to_monday` | `payouts.build_weekly_payout` (normalization) |
| `...::test_adjacent_weeks_and_other_farmers_are_excluded` | `payouts.build_weekly_payout` (accounting_date) |
| `...::test_records_already_in_a_payout_are_not_reassigned` | `payouts.build_weekly_payout` (exclusivity) |
| `...::test_repeated_generation_does_not_duplicate_and_refreshes_membership` | `payouts.build_weekly_payout` |
| `...::test_generation_refreshes_stale_draft_totals` | `payouts.build_weekly_payout` (`_refresh_totals`) |
| `...::test_empty_week_creates_no_payout_for_any_day_in_the_week` | `payouts.build_weekly_payout` (empty week) |
| `...::test_supplementary_generation_does_not_change_outstanding` | `payouts.build_weekly_payout` + `advances` |
| `...::test_concurrent_generation_creates_one_draft_and_assigns_each_once` | `payouts.build_weekly_payout` (farmer lock) |
| `tests/integration/test_corrections.py::test_correction_inherits_farmer_and_stores_magnitude` (x2) | `corrections.record_correction` |
| `...::test_correction_requires_finalised_or_paid_original` (x2) | `corrections.record_correction` (`ValidationError`) |
| `...::test_correction_is_stamped_with_business_date` | `corrections.record_correction` / `clock` |
| `...::test_credit_note_increases_next_payout` | `corrections.record_correction` + `payouts.build_weekly_payout` |
| `...::test_debit_note_decreases_next_payout` | `corrections.record_correction` + `payouts.build_weekly_payout` |
| `...::test_correction_joining_a_finalised_week_needs_a_supplementary` | `corrections.record_correction` + `payouts.build_weekly_payout` |
| `...::test_correction_is_included_once_and_original_snapshot_is_unchanged` | `corrections.record_correction` + `payouts.build_weekly_payout` |
| `...::test_correction_accepts_an_injected_business_clock` | `corrections.record_correction` (injected `clock=`) |

`tests/unit/test_clock.py` covers the clock/date helpers directly
(`business_date`, `week_*`, `business_week_bounds`, context-local `use_clock`),
including an instant whose UTC date differs from its IST date. M1 business-clock
and week-policy model tests live in `tests/integration/test_weekly_policy.py`
(unmarked).
