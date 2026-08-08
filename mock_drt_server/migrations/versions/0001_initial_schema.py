"""Initial DRT schema.

Revision ID: 0001
Revises: None
"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "stops" not in tables:
        op.create_table(
            "stops",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
        )

    if "vehicles" not in tables:
        op.create_table(
            "vehicles",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
            sa.Column("nearest_stop_id", sa.String(), sa.ForeignKey("stops.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("current_call_id", sa.String(), nullable=True),
            sa.Column("roaming_start_latitude", sa.Float(), nullable=True),
            sa.Column("roaming_start_longitude", sa.Float(), nullable=True),
            sa.Column("roaming_end_latitude", sa.Float(), nullable=True),
            sa.Column("roaming_end_longitude", sa.Float(), nullable=True),
            sa.Column("roaming_started_at", sa.DateTime(), nullable=True),
            sa.Column("roaming_arrival_at", sa.DateTime(), nullable=True),
        )
    else:
        _add_missing_columns(
            "vehicles",
            {
                "roaming_start_latitude": sa.Float(),
                "roaming_start_longitude": sa.Float(),
                "roaming_end_latitude": sa.Float(),
                "roaming_end_longitude": sa.Float(),
                "roaming_started_at": sa.DateTime(),
                "roaming_arrival_at": sa.DateTime(),
            },
        )

    if "calls" not in tables:
        op.create_table(
            "calls",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("vehicle_id", sa.String(), sa.ForeignKey("vehicles.id"), nullable=False),
            sa.Column("departure_stop_id", sa.String(), sa.ForeignKey("stops.id"), nullable=False),
            sa.Column("arrival_stop_id", sa.String(), sa.ForeignKey("stops.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("estimated_arrival_seconds", sa.Integer(), nullable=False),
            sa.Column("approach_start_latitude", sa.Float(), nullable=True),
            sa.Column("approach_start_longitude", sa.Float(), nullable=True),
            sa.Column("approach_travel_seconds", sa.Integer(), nullable=True),
            sa.Column("stop_to_stop_travel_seconds", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    else:
        _add_missing_columns(
            "calls",
            {
                "approach_start_latitude": sa.Float(),
                "approach_start_longitude": sa.Float(),
                "approach_travel_seconds": sa.Integer(),
                "stop_to_stop_travel_seconds": sa.Integer(),
            },
        )


def _add_missing_columns(table_name: str, columns: dict[str, sa.types.TypeEngine]) -> None:
    existing = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }
    for name, column_type in columns.items():
        if name not in existing:
            op.add_column(table_name, sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    op.drop_table("calls")
    op.drop_table("vehicles")
    op.drop_table("stops")
