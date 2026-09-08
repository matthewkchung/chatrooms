"""Initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-08

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_messages_room_id"),
        "messages",
        ["room_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_messages_posted_at"),
        "messages",
        ["posted_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_messages_posted_at"),
        table_name="messages",
    )

    op.drop_index(
        op.f("ix_messages_room_id"),
        table_name="messages",
    )

    op.drop_table("messages")
    op.drop_table("rooms")
