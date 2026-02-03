"""add insurance fields

Revision ID: 43d22c4ec0c7
Revises:
Create Date: 2026-01-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '43d22c4ec0c7'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'products', sa.Column('insurance_percentage', sa.Float(), nullable=True)
    )
    op.create_check_constraint(
        'ck_products_insurance_percentage_positive',
        'products',
        'insurance_percentage IS NULL OR insurance_percentage > 0',
    )

    op.add_column(
        'payment_products',
        sa.Column('insurance_applied', sa.Boolean(), server_default='false'),
    )
    op.add_column(
        'payment_products', sa.Column('insurance_price', sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('payment_products', 'insurance_price')
    op.drop_column('payment_products', 'insurance_applied')

    op.drop_constraint(
        'ck_products_insurance_percentage_positive', 'products', type_='check'
    )
    op.drop_column('products', 'insurance_percentage')
