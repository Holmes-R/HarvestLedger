# Coverage summary (M2 verification)

Measured on 18 October 2026 with Python 3.12.14 and an isolated local
PostgreSQL 17.5 test database. From `backend/`:

```bash
python -m pytest --reuse-db -q -ra --cov=procurement --cov-report=term --cov-report=json:.venv/part2_checks/final_coverage.json
```

Result: **325 passed**, exit code 0, with no reported skips or xfails.
The complete `procurement` package had **1,119 statements, 50 missed**, or
**95.53%** (96% in the terminal report). The `procurement.services` modules
had **623 statements, 25 missed**, or **95.99%**. These figures come from the
same coverage JSON report. The 80% service target is met; line coverage alone
does not establish correctness of every rule.

| Module | Coverage |
|---|---:|
| `precision.py` | 86% |
| `services/advances.py` | 98% |
| `services/corrections.py` | 88% |
| `services/delivery.py` | 96% |
| `services/errors.py` | 100% |
| `services/ledger.py` | 99% |
| `services/money.py` | 94% |
| `services/payouts.py` | 95% |
| `services/pricing.py` | 95% |
| `services/validation.py` | 80% |

The separately executed temporary Part 1 and Part 2 probes passed 43 and 12
cases respectively. They are not included in the 324-test coverage run. The
relevant failing scenarios are also covered by tracked tests, including
`tests/integration/test_part2_regressions.py`.
