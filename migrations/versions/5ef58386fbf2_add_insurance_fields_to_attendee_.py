"""add insurance fields to attendee_products

Revision ID: 5ef58386fbf2
Revises: 43d22c4ec0c7
Create Date: 2026-02-04 17:03:26.160134

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ef58386fbf2'
down_revision: Union[str, Sequence[str], None] = '43d22c4ec0c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'attendee_products',
        sa.Column('insurance_applied', sa.Boolean(), server_default='false'),
    )
    op.add_column(
        'attendee_products', sa.Column('insurance_price', sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('attendee_products', 'insurance_price')
    op.drop_column('attendee_products', 'insurance_applied')
