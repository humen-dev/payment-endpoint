"""Base shop schema provided with the task (users, products, carts, payment methods).

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

BASE_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "sql" / "base_schema.sql"


def upgrade() -> None:
    op.execute(BASE_SCHEMA_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE user_payment_methods, cart_items, carts, products, users")
