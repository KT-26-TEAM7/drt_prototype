"""Add route geometry to vehicle movement segments.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("roaming_route_coordinates", sa.Text(), nullable=True),
    )
    op.add_column(
        "vehicles",
        sa.Column("roaming_route_source", sa.String(), nullable=True),
    )
    op.add_column(
        "calls",
        sa.Column("approach_route_coordinates", sa.Text(), nullable=True),
    )
    op.add_column(
        "calls",
        sa.Column("approach_route_source", sa.String(), nullable=True),
    )
    op.add_column(
        "calls",
        sa.Column("service_route_coordinates", sa.Text(), nullable=True),
    )
    op.add_column(
        "calls",
        sa.Column("service_route_source", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calls", "service_route_source")
    op.drop_column("calls", "service_route_coordinates")
    op.drop_column("calls", "approach_route_source")
    op.drop_column("calls", "approach_route_coordinates")
    op.drop_column("vehicles", "roaming_route_source")
    op.drop_column("vehicles", "roaming_route_coordinates")
