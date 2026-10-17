# HarvestLedger

Problem 4 — Produce Procurement & Payout

A buying-centre application for recording produce deliveries, applying
effective-dated prices and moisture deductions, and generating weekly
farmer payouts with advance recovery.

## 1. Title and one-liner

- Project name and problem number.
- One sentence explaining what the application does.

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
| Database | PostgreSQL |
| Tests | pytest, pytest-django and pytest-cov |
| Local environment | Docker Compose |
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

Document:
- Prerequisites and exact versions.
- Repository cloning.
- Dependency installation.
- Environment-file setup.
- Database creation.
- Migration and seed commands.
- Backend start command.
- Frontend start command.
- One-command Docker Compose setup.

Explain every environment variable.

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

Include:
- One command to run all backend tests.
- Coverage generation command.
- Actual overall backend coverage.
- Actual business-rules coverage.
- Location of the committed coverage summary.
- Unit, integration, API and concurrency test descriptions.
- Deliberately uncovered areas and reasons.

Do not enter projected coverage percentages.

## 7. API overview

| Method | Endpoint | Purpose | Main error codes |
|---|---|---|---|
| POST | /api/v1/deliveries/preview/ | Preview calculation | 400, 404, 422 |
| POST | /api/v1/deliveries/ | Create delivery | 400, 404, 422 |
| POST | /api/v1/payouts/generate/ | Generate weekly draft | 400, 404, 409, 422 |
| POST | /api/v1/payouts/{id}/finalise/ | Finalise payout | 404, 409, 422 |

Add every implemented endpoint.
Explain pagination, filters and decimal-string responses.
Link the OpenAPI documentation.

## 8. Business rules and assumptions

Map all seven assignment rules to implementation and tests.

| Rule | Enforced in | Tested in |
|---|---|---|
| Effective-dated pricing | services/price_resolver.py | test_prices.py |
| Moisture deduction | services/delivery_math.py | test_delivery_math.py |
| Frozen delivery breakdown | services/delivery_service.py | test_deliveries.py |
| Weekly payout selection | services/payout_service.py | test_payouts.py |
| Advance recovery | services/advance_service.py and payout_service.py | test_advances.py |
| Immutability and corrections | services/correction_service.py and payout_service.py | test_corrections.py |
| Delivery validation | services/delivery_service.py | test_deliveries.py |

List numbered assumptions covering:
1. Weight, moisture and money precision.
2. Advance-recovery rounding.
3. IST business dates and UTC timestamps.
4. Draft refresh and edit behaviour.
5. Late deliveries and supplementary payouts.
6. Correction-note signs and timing.
7. Zero or negative correction totals.
8. Empty payouts and repeated state-change requests.

## 9. Error handling and logging

Explain:
- Validation errors.
- Business-rule violations.
- State conflicts.
- Expected database conflicts.
- Unexpected failures and transaction rollback.

Show the actual error-response shape.

Document logging fields, levels, request IDs,
sensitive-data exclusions and hosted log access.

## 10. Reviewer aids

Include:
- Seed command and available demo scenarios.
- Sample requests or example inputs.
- Reviewer-clock instructions and safeguards.
- How to reproduce the listed edge cases.
- Safe reseeding instructions.

## 11. Known limitations

State actual limitations honestly.

Distinguish:
- Incomplete Core requirements.
- Documented design restrictions.
- Unimplemented optional Stretch features.

## 12. AI and third-party usage

Disclose:
- AI tools used.
- What each tool helped with.
- Templates or third-party snippets used.
- Relevant licences or attribution.

Link to [PROMPTS.md](PROMPTS.md).