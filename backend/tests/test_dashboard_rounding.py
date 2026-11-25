"""Fix 3: revenue is rounded to cents once, on the exact Decimal (half-up).

Unit test: no database or Redis; the revenue service and auth are faked.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import dashboard
from app.core.auth import authenticate_request


class FakeUser:
    tenant_id = "tenant-a"


def client_with_total(monkeypatch, total):
    async def fake_summary(property_id, tenant_id):
        return {"property_id": property_id, "tenant_id": tenant_id,
                "total": total, "currency": "USD", "count": 1}

    monkeypatch.setattr(dashboard, "get_revenue_summary", fake_summary)
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api/v1")
    app.dependency_overrides[authenticate_request] = lambda: FakeUser()
    return TestClient(app)


@pytest.mark.parametrize("stored_total, shown", [
    ("1000.005", 1000.01),  # float(...) first gives 1000.00499... -> 1000.00
    ("2250.000", 2250.00),
    ("4975.504", 4975.50),
    ("0.00", 0.00),
])
def test_total_is_rounded_to_cents_half_up(monkeypatch, stored_total, shown):
    client = client_with_total(monkeypatch, stored_total)
    r = client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"})
    assert r.status_code == 200
    assert r.json()["total_revenue"] == shown
