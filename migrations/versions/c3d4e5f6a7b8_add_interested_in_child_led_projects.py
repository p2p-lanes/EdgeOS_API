"""add interested_in_child_led_projects to applications

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'applications',
        sa.Column('interested_in_child_led_projects', sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('applications', 'interested_in_child_led_projects')
