"""Fix 4: a database failure must show an error, never mock or another tenant's figures.

Unit tests: no database or Redis; the pool and auth are faked.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import dashboard
from app.core.auth import authenticate_request
from app.core.database_pool import DatabasePool
from app.services.reservations import calculate_total_revenue


class FakeUser:
    tenant_id = "tenant-b"


def test_service_raises_instead_of_returning_mock_data(monkeypatch):
    async def broken_initialize(self):
        self.session_factory = None  # what a failed pool init leaves behind

    monkeypatch.setattr(DatabasePool, "initialize", broken_initialize)

    # The old code returned {'total': '4975.50', 'count': 4}: tenant-a's prop-002 figures.
    with pytest.raises(Exception):
        asyncio.run(calculate_total_revenue("prop-002", "tenant-b"))


def test_endpoint_returns_503_without_figures(monkeypatch):
    async def failing_summary(property_id, tenant_id):
        raise RuntimeError("database down")

    monkeypatch.setattr(dashboard, "get_revenue_summary", failing_summary)
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api/v1")
    app.dependency_overrides[authenticate_request] = lambda: FakeUser()

    r = TestClient(app).get("/api/v1/dashboard/summary", params={"property_id": "prop-002"})

    assert r.status_code == 503
    assert r.json() == {"detail": "Revenue data temporarily unavailable"}
