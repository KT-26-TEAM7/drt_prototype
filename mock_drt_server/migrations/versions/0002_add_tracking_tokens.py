"""Add public tracking tokens.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tracking_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "call_id",
            sa.String(),
            sa.ForeignKey("calls.id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_tracking_tokens_call_id",
        "tracking_tokens",
        ["call_id"],
        unique=True,
    )
    op.create_index(
        "ix_tracking_tokens_token_hash",
        "tracking_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tracking_tokens_token_hash", table_name="tracking_tokens")
    op.drop_index("ix_tracking_tokens_call_id", table_name="tracking_tokens")
    op.drop_table("tracking_tokens")
