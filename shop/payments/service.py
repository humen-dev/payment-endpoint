"""Starts the payment for a cart.

The flow has two short transactions with the provider call between them, so no database
lock or transaction is held while we wait for the network:

1. Lock the cart, validate it and save a `pending` payment.
2. Charge the card.
3. Save the provider result; on success mark the cart as checked out.

Double charges are prevented on two levels:
* the Idempotency-Key: a repeated request gets the result of the first one;
* the `uq_payments_cart_active` index: one pending or succeeded payment per cart.
"""

import uuid

from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from shop.errors import BadGateway, Conflict, NotFound, Unprocessable
from shop.extensions import db
from shop.models import Cart, CartStatus, Payment, PaymentStatus, UserPaymentMethod
from shop.payments import provider
from shop.payments.totals import calculate_cart_total


def start_payment(
    user_id: uuid.UUID,
    cart_id: uuid.UUID,
    idempotency_key: str,
    payment_method_id: uuid.UUID | None = None,
) -> Payment:
    """Returns a `succeeded` or `failed` payment. Never returns a `pending` one."""
    cart = _lock_user_cart(user_id, cart_id)

    previous_payment = _find_payment_by_idempotency_key(user_id, idempotency_key)
    if previous_payment is not None:
        return _replay(previous_payment, cart_id, payment_method_id)

    payment = _create_pending_payment(cart, idempotency_key, payment_method_id)
    return _charge(payment)


def _lock_user_cart(user_id: uuid.UUID, cart_id: uuid.UUID) -> Cart:
    """Locks the cart row, so concurrent payments for one cart run one after another."""
    cart = db.session.scalars(
        select(Cart)
        .where(Cart.id == cart_id, Cart.user_id == user_id)
        .with_for_update()
    ).one_or_none()
    # A cart of another user is reported as missing, so we do not reveal that it exists.
    if cart is None:
        raise NotFound("cart_not_found", "Cart not found.")
    return cart


def _find_payment_by_idempotency_key(
    user_id: uuid.UUID, idempotency_key: str
) -> Payment | None:
    return db.session.scalars(
        select(Payment).where(
            Payment.user_id == user_id, Payment.idempotency_key == idempotency_key
        )
    ).one_or_none()


def _replay(
    payment: Payment, cart_id: uuid.UUID, payment_method_id: uuid.UUID | None
) -> Payment:
    """Returns the result of the first request made with the same idempotency key."""
    is_same_request = payment.cart_id == cart_id and payment_method_id in (
        None,
        payment.payment_method_id,
    )
    if not is_same_request:
        raise Unprocessable(
            "idempotency_key_reused",
            "This Idempotency-Key was already used for another request.",
        )
    if payment.status == PaymentStatus.PENDING:
        raise _payment_in_progress()
    return payment


def _payment_in_progress() -> Conflict:
    return Conflict("payment_in_progress", "The payment is in progress. Retry later.")


def _create_pending_payment(
    cart: Cart, idempotency_key: str, payment_method_id: uuid.UUID | None
) -> Payment:
    if cart.status != CartStatus.ACTIVE:
        raise Conflict(
            "cart_not_active", f"The cart is {cart.status}, it cannot be paid."
        )
    if not cart.items:
        raise Unprocessable("cart_empty", "The cart is empty.")

    total = calculate_cart_total(cart)
    if total.amount <= 0:
        raise Unprocessable(
            "nothing_to_pay", "The cart total must be greater than zero."
        )

    payment = Payment(
        cart=cart,
        user_id=cart.user_id,
        payment_method=_find_payment_method(cart.user_id, payment_method_id),
        amount=total.amount,
        currency=total.currency,
        idempotency_key=idempotency_key,
    )
    db.session.add(payment)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        # Another request created a payment for this cart or with this key first.
        if isinstance(error.orig, UniqueViolation):
            raise _payment_in_progress()
        raise
    return payment


def _find_payment_method(
    user_id: uuid.UUID, payment_method_id: uuid.UUID | None
) -> UserPaymentMethod:
    """Returns the requested payment method of the user, or the default one."""
    query = select(UserPaymentMethod).where(UserPaymentMethod.user_id == user_id)
    if payment_method_id is None:
        # The base schema does not enforce one default per user, so take the newest one.
        query = query.where(UserPaymentMethod.is_default).order_by(
            UserPaymentMethod.created_at.desc()
        )
    else:
        query = query.where(UserPaymentMethod.id == payment_method_id)

    payment_method = db.session.scalars(query.limit(1)).first()
    if payment_method is None:
        raise Unprocessable("payment_method_not_found", "No payment method to charge.")
    return payment_method


def _charge(payment: Payment) -> Payment:
    try:
        result = provider.charge(
            token=payment.payment_method.provider_token,
            amount=payment.amount,
            currency=payment.currency,
            idempotency_key=str(payment.id),
        )
    except provider.ProviderUnavailableError:
        # The card may have been charged, so the payment must not be marked as `failed`:
        # that would let the user pay again. It stays `pending` until reconciliation.
        raise BadGateway(
            "provider_unavailable",
            f"The payment provider did not answer. Payment {payment.id} is pending.",
        )

    if result.succeeded:
        payment.status = PaymentStatus.SUCCEEDED
        payment.provider_payment_id = result.provider_payment_id
        payment.cart.status = CartStatus.CHECKED_OUT
    else:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = result.failure_reason
    db.session.commit()
    return payment
