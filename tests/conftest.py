import sys
from pathlib import Path
from typing import Any

import pytest

CONTROL_PLANE_DIR = Path(__file__).parent.parent / "control-plane"
sys.path.insert(0, str(CONTROL_PLANE_DIR))

# Test tenants are named "<prefix>-<8 hex>" by each suite's own `_tenant` helper.
# Their workloads are swept per-file by namespace ("fake-%"), but the tenant rows
# themselves were never cleaned up, so every run left more behind — visible once
# Phase 6 started reporting one metric series per tenant. New suites should keep
# to this slug shape so this sweep keeps finding them.
TEST_TENANT_SLUG_PATTERN = "^(t|m)-[0-9a-f]{8}$"


@pytest.fixture(scope="session", autouse=True)
def _sweep_test_tenants() -> Any:
    """Delete tenants created by the test suites, and their dependent rows.

    Session-scoped so it costs one statement batch per run rather than one per
    test, and deliberately pattern-matched: hand-made demo tenants (seed scripts,
    live checkpoints) don't match and are left alone.
    """
    yield

    from sqlalchemy import delete, select, text

    from db import SessionLocal
    from db.models import ApiKey, AutoscaleEvent, BillingSnapshot, Tenant, UsageEvent, Workload

    session = SessionLocal()
    try:
        doomed = select(Tenant.id).where(text("slug ~ :pat")).params(pat=TEST_TENANT_SLUG_PATTERN)
        workloads = select(Workload.id).where(Workload.tenant_id.in_(doomed))
        # Children first: usage/autoscale rows reference workloads, everything else
        # references the tenant.
        session.execute(delete(AutoscaleEvent).where(AutoscaleEvent.workload_id.in_(workloads)))
        session.execute(delete(UsageEvent).where(UsageEvent.tenant_id.in_(doomed)))
        session.execute(delete(BillingSnapshot).where(BillingSnapshot.tenant_id.in_(doomed)))
        session.execute(delete(Workload).where(Workload.tenant_id.in_(doomed)))
        session.execute(delete(ApiKey).where(ApiKey.tenant_id.in_(doomed)))
        session.execute(delete(Tenant).where(Tenant.id.in_(doomed)))
        session.commit()
    except Exception:
        # Never fail a green run on cleanup — the suites that need a live database
        # already fail loudly on their own if it isn't there.
        session.rollback()
    finally:
        session.close()
