"""add calendar_subscriptions table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'calendar_subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('citizen_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['citizen_id'], ['humans.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_calendar_subscriptions_id'),
        'calendar_subscriptions',
        ['id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_calendar_subscriptions_citizen_id'),
        'calendar_subscriptions',
        ['citizen_id'],
        unique=True,
    )
    op.create_index(
        op.f('ix_calendar_subscriptions_token'),
        'calendar_subscriptions',
        ['token'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_calendar_subscriptions_token'),
        table_name='calendar_subscriptions',
    )
    op.drop_index(
        op.f('ix_calendar_subscriptions_citizen_id'),
        table_name='calendar_subscriptions',
    )
    op.drop_index(
        op.f('ix_calendar_subscriptions_id'),
        table_name='calendar_subscriptions',
    )
    op.drop_table('calendar_subscriptions')
