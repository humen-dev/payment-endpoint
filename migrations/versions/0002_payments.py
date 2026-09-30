"""Payments table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- One row per attempt to charge a cart.
        -- amount and currency are a snapshot of the cart total at the moment of payment.
        -- Status values:
        --   pending   — the payment is created, the provider has not answered yet.
        --   succeeded — the provider charged the card; the cart is checked out.
        --   failed    — the provider declined the charge; the user can try again.
        CREATE TABLE payments (
            id                  UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
            cart_id             UUID           NOT NULL REFERENCES carts(id),
            user_id             UUID           NOT NULL REFERENCES users(id),
            payment_method_id   UUID           NOT NULL REFERENCES user_payment_methods(id),
            amount              NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
            currency            CHAR(3)        NOT NULL,
            status              TEXT           NOT NULL DEFAULT 'pending'
                                               CHECK (status IN ('pending', 'succeeded', 'failed')),
            idempotency_key     TEXT           NOT NULL
                                               CHECK (length(idempotency_key) BETWEEN 1 AND 255),
            provider_payment_id TEXT,
            failure_reason      TEXT,
            created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            -- A client retries a request with the same key; the key is unique per user.
            CONSTRAINT uq_payments_user_idempotency_key UNIQUE (user_id, idempotency_key)
        );

        CREATE INDEX idx_payments_cart_id ON payments(cart_id);

        -- At most one in-flight or successful payment per cart: protects against a double charge
        -- even when a client sends different idempotency keys. Failed attempts do not block a retry.
        CREATE UNIQUE INDEX uq_payments_cart_active ON payments(cart_id)
            WHERE status IN ('pending', 'succeeded');
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE payments")
