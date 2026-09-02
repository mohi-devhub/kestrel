"""usage_events and billing_snapshots tables

Revision ID: b3d1c7a90f44
Revises: eee9ce9d2832
Create Date: 2026-09-02 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "b3d1c7a90f44"
down_revision: str | None = "eee9ce9d2832"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "workload_id", UUID(as_uuid=True), sa.ForeignKey("workloads.id"), nullable=False
        ),
        sa.Column("gpus", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("gpu_seconds", sa.Numeric(), nullable=True),
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_events_tenant_started", "usage_events", ["tenant_id", "started_at"])
    op.create_index("ix_usage_events_workload", "usage_events", ["workload_id"])

    op.create_table(
        "billing_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("period_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("period_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("total_gpu_seconds", sa.Numeric(), nullable=False),
        sa.Column("total_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("breakdown", JSONB, nullable=False),
        sa.Column("generated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_billing_snapshots_tenant", "billing_snapshots", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_billing_snapshots_tenant", table_name="billing_snapshots")
    op.drop_table("billing_snapshots")
    op.drop_index("ix_usage_events_workload", table_name="usage_events")
    op.drop_index("ix_usage_events_tenant_started", table_name="usage_events")
    op.drop_table("usage_events")
