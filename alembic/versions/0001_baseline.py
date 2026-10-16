"""Baseline: đưa database cũ (tạo bằng create_all + ALTER TABLE tay) về cùng một mốc.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: database mới được tạo đủ bảng, database cũ được bổ sung các
    # cột còn thiếu như trước đây. Từ migration 0002 trở đi dùng Alembic thuần.
    import database

    database.ensure_product_category_schema()
    database.ensure_order_tracking_schema()


def downgrade() -> None:
    pass
