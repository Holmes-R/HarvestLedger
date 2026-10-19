# Coverage summary (M3)

Measured on 19 October 2026 with Python 3.11.9 and an isolated PostgreSQL test
database. From `backend/`:

```bash
venv/Scripts/python.exe -m pytest --reuse-db -q -ra --cov=procurement --cov-report=term --cov-report=json:coverage.json
```

Result: **527 passed** (325 M1+M2 regression + 202 API), exit code 0, with no
reported skips or xfails. The API figure includes the 13-test API01–API12
acceptance matrix (`tests/api/test_acceptance_matrix.py`).

- Whole `procurement` package: **2,191 statements, 97 missed**, **96%**.
- `procurement.services` (business rules): **627 statements, 26 missed**,
  **~96%** — the 80% service target is met.
- `procurement.api` (M3 HTTP layer): **1,068 statements, 46 missed**, **~96%**.

Line coverage alone does not establish correctness of every rule.

| Module | Coverage |
|---|---:|
| `api/errors.py` | 85% |
| `api/filters.py` | 96% |
| `api/middleware.py` | 97% |
| `api/pagination.py` | 100% |
| `api/schema.py` | 98% |
| `api/serializers.py` | 97% |
| `api/views.py` | 98% |
| `precision.py` | 86% |
| `services/advances.py` | 98% |
| `services/corrections.py` | 88% |
| `services/delivery.py` | 96% |
| `services/errors.py` | 100% |
| `services/ledger.py` | 98% |
| `services/money.py` | 94% |
| `services/payouts.py` | 95% |
| `services/pricing.py` | 95% |
| `services/validation.py` | 80% |

The lower figures in `services/validation.py`, `services/corrections.py` and
`api/errors.py` come from defensive branches that raise on paths the normal flow
cannot reach (for example, re-checking ownership after a lock, or handling a
non-DRF exception). They are exercised by construction, not by every test.
