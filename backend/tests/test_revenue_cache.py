"""Fix 1: cached revenue must never be shared between tenants.

Integration test: needs the docker-compose Postgres and Redis.
`prop-001` exists for both tenant-a (4 bookings) and tenant-b (0 bookings).
"""

import asyncio

from app.services.cache import get_revenue_summary, redis_client


async def _clear_revenue_cache():
    keys = await redis_client.keys("revenue:*")
    if keys:
        await redis_client.delete(*keys)


def test_same_property_id_is_cached_per_tenant():
    async def scenario():
        await _clear_revenue_cache()
        tenant_a = await get_revenue_summary("prop-001", "tenant-a")  # fills the cache
        tenant_b = await get_revenue_summary("prop-001", "tenant-b")  # must not read it
        await _clear_revenue_cache()
        return tenant_a, tenant_b

    tenant_a, tenant_b = asyncio.run(scenario())

    assert tenant_a["count"] == 4
    assert tenant_b["count"] == 0
    assert tenant_b["tenant_id"] == "tenant-b"
