"""Fix 2: monthly revenue uses the property's time zone, not UTC.

Integration test: needs the docker-compose Postgres (seeded from database/seed.sql).
res-tz-1 (tenant-a, prop-001, Paris) checks in at 2024-02-29 23:30 UTC,
which is 2024-03-01 00:30 in Paris, so it belongs to March.
"""

import asyncio
from decimal import Decimal

from app.services.reservations import calculate_monthly_revenue


def monthly(property_id, tenant_id, month, year):
    return asyncio.run(calculate_monthly_revenue(property_id, tenant_id, month, year))


def test_late_utc_check_in_counts_in_local_month():
    # 1250.000 (res-tz-1) + 333.333 + 333.333 + 333.334
    assert monthly("prop-001", "tenant-a", 3, 2024) == Decimal("2250.000")
    assert monthly("prop-001", "tenant-a", 2, 2024) == Decimal("0")


def test_monthly_revenue_is_scoped_to_tenant():
    # prop-001 also exists for tenant-b, with no bookings.
    assert monthly("prop-001", "tenant-b", 3, 2024) == Decimal("0")


def test_december_rolls_into_next_year():
    assert monthly("prop-001", "tenant-a", 12, 2024) == Decimal("0")
