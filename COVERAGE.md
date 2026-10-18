# Coverage summary (M3)

Measured on 18 October 2026 with Python 3.11.9 and an isolated PostgreSQL test
database. From `backend/`:

```bash
venv/Scripts/python.exe -m pytest --reuse-db -q -ra --cov=procurement --cov-report=term --cov-report=json:coverage.json
```

Result: **375 passed**, exit code 0, with no reported skips or xfails.

- Whole `procurement` package: **1,729 statements, 88 missed**, **95%**.
- `procurement.services` (business rules): **623 statements, 24 missed**,
  **~96%** — the 80% service target is met.
- `procurement.api` (M3 HTTP layer): **610 statements, 39 missed**, **~94%**.

Line coverage alone does not establish correctness of every rule.

| Module | Coverage |
|---|---:|
| `api/errors.py` | 80% |
| `api/serializers.py` | 97% |
| `api/views.py` | 96% |
| `precision.py` | 86% |
| `services/advances.py` | 98% |
| `services/corrections.py` | 88% |
| `services/delivery.py` | 96% |
| `services/errors.py` | 100% |
| `services/ledger.py` | 100% |
| `services/money.py` | 94% |
| `services/payouts.py` | 95% |
| `services/pricing.py` | 95% |
| `services/validation.py` | 80% |

The lower figures in `services/validation.py`, `services/corrections.py` and
`api/errors.py` come from defensive branches that raise on paths the normal flow
cannot reach (for example, re-checking ownership after a lock, or handling a
non-DRF exception). They are exercised by construction, not by every test.
