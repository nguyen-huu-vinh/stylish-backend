"""Trả hàng/hoàn tiền, refresh token, xác minh email.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    from database import Base

    bind = op.get_bind()
    # Bảng mới (bỏ qua nếu 0001 đã tạo sẵn trên database trống)
    for name in ("email_verification_otps", "refresh_tokens", "return_requests"):
        Base.metadata.tables[name].create(bind, checkfirst=True)

    if "email_verified" not in _columns("users"):
        # Tài khoản đã tồn tại coi như đã xác minh
        op.add_column(
            "users",
            sa.Column(
                "email_verified", sa.Boolean(), nullable=False,
                server_default=sa.true(),
            ),
        )
    order_columns = _columns("orders")
    if "refund_amount" not in order_columns:
        op.add_column("orders", sa.Column("refund_amount", sa.Float(), nullable=True))
    if "refunded_at" not in order_columns:
        op.add_column("orders", sa.Column("refunded_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "refunded_at")
    op.drop_column("orders", "refund_amount")
    op.drop_column("users", "email_verified")
    for name in ("return_requests", "refresh_tokens", "email_verification_otps"):
        op.drop_table(name)
