"""add variable price fields

Revision ID: a1b2c3d4e5f6
Revises: 5ef58386fbf2
Create Date: 2026-02-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '5ef58386fbf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('min_price', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('max_price', sa.Float(), nullable=True))

    op.create_check_constraint(
        'ck_products_min_price_positive',
        'products',
        'min_price IS NULL OR min_price > 0',
    )
    op.create_check_constraint(
        'ck_products_max_price_positive',
        'products',
        'max_price IS NULL OR max_price > 0',
    )
    op.create_check_constraint(
        'ck_products_max_gte_min_price',
        'products',
        'max_price IS NULL OR min_price IS NULL OR max_price >= min_price',
    )


def downgrade() -> None:
    op.drop_constraint('ck_products_max_gte_min_price', 'products', type_='check')
    op.drop_constraint('ck_products_max_price_positive', 'products', type_='check')
    op.drop_constraint('ck_products_min_price_positive', 'products', type_='check')

    op.drop_column('products', 'max_price')
    op.drop_column('products', 'min_price')
