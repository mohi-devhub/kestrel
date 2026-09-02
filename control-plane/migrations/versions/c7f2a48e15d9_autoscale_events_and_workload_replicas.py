"""autoscale_events table and workload replica tracking

Revision ID: c7f2a48e15d9
Revises: b3d1c7a90f44
Create Date: 2026-09-02 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "c7f2a48e15d9"
down_revision: str | None = "b3d1c7a90f44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workloads", sa.Column("replicas", sa.Integer(), nullable=True))
    op.create_table(
        "autoscale_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workload_id", UUID(as_uuid=True), sa.ForeignKey("workloads.id"), nullable=False
        ),
        sa.Column("from_replicas", sa.Integer(), nullable=False),
        sa.Column("to_replicas", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_autoscale_events_workload_at", "autoscale_events", ["workload_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_autoscale_events_workload_at", table_name="autoscale_events")
    op.drop_table("autoscale_events")
    op.drop_column("workloads", "replicas")
