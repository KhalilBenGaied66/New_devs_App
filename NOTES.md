# Notes: Property Revenue Dashboard debugging

## How to run
```
docker compose up --build -d
```
Frontend http://localhost:3000 · API docs http://localhost:8000/docs · Postgres on host port 5433 · Redis on host port 6380.

Tests (integration, against the seeded compose database and Redis):
```
docker compose exec backend pip install pytest
docker compose exec backend python -m pytest
```

## Bugs: found by / root cause / fix / proof

### 0. Setup: the backend never read the database (FIXED)
- **Found by:** logged in as both clients, `GET /api/v1/dashboard/summary?property_id=prop-001`. Both got `1000.0 / 3 bookings`, the hard-coded mock values in `reservations.py`. Backend log: `'Settings' object has no attribute 'supabase_db_user'`, then `greenlet` missing.
- **Root cause:** `core/database_pool.py` built its URL from Supabase settings that don't exist (ignoring `DATABASE_URL` from docker-compose), passed `QueuePool` to an async engine (not allowed), and `get_session()` was `async def` but called with `async with`. `greenlet` (needed by async SQLAlchemy) was missing from `requirements.txt`. The service catches every error and silently returns mock numbers, which hid all of this.
- **Fix:** URL from `settings.database_url` with the asyncpg driver; default async pool; `get_session()` is a plain function; `greenlet` added to `requirements.txt` (already in `uv.lock`).
- **Proof:** `tests/test_database_pool.py` (3 tests). Sunset `prop-001` now shows the real `2250.0 / 4 bookings`.

### 1. Ocean Rentals sees another company's revenue (privacy) (FIXED)
- **Found by:** with real data, Sunset loads `prop-001` (2250.0 / 4), then Ocean loads `prop-001` and also sees **2250.0 / 4**, though Ocean's own `prop-001` (Mountain Lodge Beta) has 0 bookings. Redis had a single key, `revenue:prop-001`.
- **Root cause:** `services/cache.py` cached under `revenue:{property_id}`. Property IDs are only unique per tenant (`properties` PK is `(id, tenant_id)`), and `prop-001` exists for both tenants, so whoever loaded it first filled the cache and the other tenant read it for 5 minutes ("sometimes, when we refresh").
- **Fix:** key is now `revenue:{tenant_id}:{property_id}` (same pattern as `bootstrap:{user_id}:{tenant_id}` in `bootstrap.py`). One line.
- **Proof:** `tests/test_revenue_cache.py` fails without the fix (`assert 4 == 0`) and passes with it. Live: Sunset `prop-001` = 2250.0 / 4, Ocean `prop-001` = 0.0 / 0 on every refresh; Redis keys `revenue:tenant-a:prop-001` and `revenue:tenant-b:prop-001`.

### 2. Sunset's March totals don't match (FIXED)
- **Found by:** reading the seed: `res-tz-1` (Sunset, `prop-001`, Paris) checks in 2024-02-29 23:30 UTC = **2024-03-01 00:30 in Paris**, a March booking. Querying March with UTC boundaries (what the code did) gives **1000.000**; Sunset's own records (Paris time) say **2250.000**. 1000.00 / 3 bookings is also exactly what Sunset saw while the mock fallback was active.
- **Root cause:** `calculate_monthly_revenue` in `services/reservations.py` built month boundaries as naive UTC datetimes and ignored `properties.timezone`. It was also a stub (always returned 0) and its SQL used a `tenant_id` the function never received.
- **Fix:** the existing function now runs its query (same `DatabasePool` + `text()` pattern as `calculate_total_revenue`), takes `tenant_id`, and compares `check_in_date AT TIME ZONE p.timezone` (joined from `properties`) against local month boundaries. Postgres does the time-zone conversion, including DST. Removed the debug `print`.
- **Proof:** `tests/test_monthly_revenue.py`: March 2024 = 2250.000 (res-tz-1 included), February = 0, tenant-b's `prop-001` = 0, December rolls into the next year.

### 3. Totals off by a few cents (FIXED)
- **Found by:** following the total from the database to the screen. `database/schema.sql` stores `total_amount NUMERIC(10,3)` (sub-cent, e.g. 333.333 + 333.333 + 333.334). `api/v1/dashboard.py` line 18 turns the exact `Decimal` total into a `float`. `frontend/src/components/RevenueSummary.tsx` then rounds that float again with `Math.round(x * 100) / 100`, and even has a "Precision Mismatch Detected" warning, so the original authors had seen the symptom.
- **Root cause:** money passes through binary floating point before it is rounded. A total like `1000.005` becomes the float `1000.00499…`, which rounds to **1000.00** instead of **1000.01**. Only totals that land on a half cent are affected, which matches "a few cents here and there, can't pin down when". Checked in the container: `round(float("1000.005"), 2)` = 1000.0, `Decimal("1000.005").quantize(0.01, ROUND_HALF_UP)` = 1000.01.
- **Fix:** `dashboard.py` rounds the exact `Decimal` total once, to cents, half-up (`quantize(Decimal("0.01"), ROUND_HALF_UP)`), and only then converts it for JSON. The response field stays a number, so the frontend is unchanged.
- **Proof:** `tests/test_dashboard_rounding.py` (unit test, auth and revenue service faked): on the original code 2 of 4 cases fail (`1000.005` is sent raw instead of `1000.01`; `4975.504` instead of `4975.50`); with the fix all pass. Live, all six properties match the seed sums (Sunset 2250.00 / 4975.50 / 6100.50; Ocean 0.00 / 1776.50 / 3256.00).

## Change log (every file touched)
| File | What changed | Bug |
|---|---|---|
| `backend/app/core/database_pool.py` | URL from `settings.database_url` (asyncpg driver); removed `QueuePool` + its import; `get_session()` no longer `async` | 0 |
| `backend/requirements.txt` | added `greenlet` | 0 |
| `backend/tests/test_database_pool.py` | new: pool connects; revenue = 4 real bookings, not mock 3 | 0 |
| `backend/app/services/cache.py` | cache key `revenue:{property_id}` → `revenue:{tenant_id}:{property_id}` | 1 |
| `backend/tests/test_revenue_cache.py` | new: same property ID, two tenants, separate results | 1 |
| `backend/app/services/reservations.py` | `calculate_monthly_revenue`: real query, `tenant_id` param, local-time month via `AT TIME ZONE p.timezone`, debug print removed | 2 |
| `backend/tests/test_monthly_revenue.py` | new: March = 2250.000 incl. res-tz-1, Feb = 0, tenant scope, December rollover | 2 |
| `backend/app/api/v1/dashboard.py` | `float(total)` → `Decimal(total).quantize(0.01, ROUND_HALF_UP)`, then to JSON number | 3 |
| `backend/tests/test_dashboard_rounding.py` | new: half-cent totals round up, exact totals unchanged | 3 |
| `NOTES.md` | this file | all |

## Decisions (one line each)
- Ran the repo's own docker-compose, unchanged.
- First frontend build failed on a network reset during `npm install`; a plain rebuild worked. No code change.
- Follow the repo's conventions: tests in `backend/tests/test_*.py` (pyproject `testpaths`, pre-commit `name-tests-test`), ruff, conventional commit messages (`fix: ...`).
- Assignment says "do NOT rebuild, use existing patterns": every fix is the smallest change to existing code.
- Did **not** add a property-ownership check (404) to the dashboard endpoint: new logic, and not needed once the DB works, because the existing SQL already filters by `tenant_id`. Ocean asking for `prop-002` gets its own 0, not Sunset's figure.
- Rounding: half-up to cents, once, on the server (the usual rule for invoices); the frontend's own `Math.round` is left as is, since it now only ever receives 2-decimal values.
- Tests for bugs 0–2 are integration tests against the compose services (no new test dependencies added to the repo); pytest installed in the container only to run them.

## Other risks noticed
Planned next (real bugs in existing code, small fixes):
- `calculate_total_revenue` swallows every DB error and returns hard-coded mock numbers (with another tenant's figures for some IDs), so a DB outage shows wrong data as if real. This is what hid bug 0.
- A new DB engine is created on every request (`DatabasePool()` inside `calculate_total_revenue`) and never closed, instead of reusing the global pool: connections leak under load.

Not fixed, on purpose:
- Frontend `Dashboard.tsx` hard-codes all 5 properties (with tenant-a's names) for every client. **Why not:** a real fix needs a new "list my properties" endpoint and frontend work, which is a feature, not a bug fix ("do NOT rebuild"). No longer a leak, since the backend now filters by tenant.
- Currency is hard-coded to `"USD"`, while reservations have a `currency` column. **Why not:** every seed booking is USD, so nothing is wrong today; how to total mixed currencies (convert, or group by currency) is a product decision for the team, not a guess to make in a bug fix.
- The frontend sends an `X-Simulated-Tenant` header that no backend code reads. **Why not:** dead code, no effect; removing it is cleanup, not a fix.

## Assumptions
- A reservation's revenue belongs to the month of its **check-in date in the property's local time** (as the original query intended: `check_in_date >= start AND < end`). Not split across nights.
- `calculate_monthly_revenue` is not called by any endpoint yet; I fixed the function rather than adding a new endpoint (assignment: don't rebuild). Wiring it to a `month`/`year` dashboard parameter is a next step.

## If I had more time

## Tools used
Used Claude Code as a pair programmer. I made the design decisions, reviewed and approved every change, and can explain each one.

Note on data privacy: this exercise only contains seed data and test accounts, so nothing sensitive was shared with the AI tool. With real client data I would follow the company's AI policy, use only approved tools, and never give an AI tool real customer records, revenue figures or credentials: I would reproduce the bug with anonymised or synthetic data that has the same shape (for example, the same property-ID collision or the same half-cent total).
