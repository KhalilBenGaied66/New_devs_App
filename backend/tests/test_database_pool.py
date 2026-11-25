"""Fix 0: the revenue service must read the real database, not the mock fallback.

Integration test: needs the docker-compose Postgres (seeded from database/seed.sql).
Run inside the backend container: `docker compose exec backend python -m pytest`.
"""

import asyncio
import inspect

from app.core.database_pool import DatabasePool
from app.services.reservations import calculate_total_revenue


def test_get_session_is_a_plain_function():
    # Callers use `async with pool.get_session() as s:`, which fails on a coroutine.
    assert not inspect.iscoroutinefunction(DatabasePool.get_session)


def test_pool_connects_with_database_url():
    pool = DatabasePool()
    asyncio.run(pool.initialize())
    assert pool.session_factory is not None


def test_revenue_comes_from_the_database_not_the_mock():
    result = asyncio.run(calculate_total_revenue("prop-001", "tenant-a"))
    # Seed: res-tz-1 + res-dec-1..3 = 4 bookings. The mock fallback says 3.
    assert result["count"] == 4
