# Coverage summary (M2)

Measured with the project's configured tooling: `pytest-cov` (7.1.0) driving
`coverage` (7.16.2), both pinned in `backend/requirements.txt`. No test was
weakened, skipped or `xfail`-ed to raise these numbers; the full suite runs
green first.

## Command (run from `backend/`)

```bash
python -m pytest --reuse-db --cov=procurement --cov-report=term-missing
```

## Headline results

| Scope | Statements | Missed | Coverage |
|---|---|---|---|
| M2 business-rules layer — `procurement/services/` | 538 | 16 | **97.0%** |
| M1 domain rules — `models.py` + `precision.py` + `clock.py` | 186 | 15 | **91.9%** |
| Combined business-rules layer | 724 | 31 | **95.7%** |
| Whole backend package — `procurement/` | 1023 | 41 | **96.0%** |

Both targets are met: the business-rules layer is **95.7%** (services alone
**97.0%**), comfortably above the 80% requirement, and the whole backend is
**96.0%**.

Test totals in the same run: **274 passed** — 147 `m2`-marked, 127 M1 regression.

## Per-file breakdown

| File | Cover | Missing lines |
|---|---|---|
| `services/corrections.py` | 100% | — |
| `services/errors.py` | 100% | — |
| `services/locking.py` | 100% | — |
| `services/money.py` | 100% | — |
| `services/ledger.py` | 99% | 96 |
| `services/advances.py` | 98% | 69 |
| `services/pricing.py` | 98% | 119 |
| `services/delivery.py` | 96% | 157, 192, 194, 223, 359, 393 |
| `services/payouts.py` | 94% | 80, 82, 144, 157, 202 |
| `services/validation.py` | 80% | 20-21 |
| `clock.py` | 96% | 116, 120 |
| `models.py` | 93% | 65, 91, 110, 139, 161, 214, 338 |
| `precision.py` | 81% | 81-84, 89, 108 |
| `management/commands/seed_data.py` | 98% | 493, 572, 584 |
| `admin.py` | 100% | — |
| `scenarios.py` | 100% | — |
| `migrations/0001_initial.py` | 100% | — |
| `migrations/0002_farmer_indian_mobile.py` | 56% | 18-30 |

## Notes on the uncovered lines

- The uncovered service lines are defensive branches (e.g. `payouts.py`
  re-validation guards reachable only through a state that cannot be built via
  the public API, `delivery.py` edit paths for records already locked into a
  payout). They are deliberately not exercised by weakening a rule; each
  corresponds to a guard whose tested counterpart is on the happy path.
- `0002_farmer_indian_mobile` is low because its `RunPython` data step runs
  during `migrate`, before coverage starts; it is a migration, not business
  logic.
- `models.py` / `precision.py` uncovered lines are `__str__` helpers and
  over-precise-input rejection paths already covered functionally elsewhere.
