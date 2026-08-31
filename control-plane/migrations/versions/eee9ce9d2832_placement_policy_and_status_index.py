"""placement policy column and status index

Revision ID: eee9ce9d2832
Revises: fa6e359b357c
Create Date: 2026-08-31 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eee9ce9d2832"
down_revision: str | None = "fa6e359b357c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workloads", sa.Column("placement_policy", sa.String(), nullable=True))
    op.create_index("ix_workloads_status", "workloads", ["status"])


def downgrade() -> None:
    op.drop_index("ix_workloads_status", table_name="workloads")
    op.drop_column("workloads", "placement_policy")
