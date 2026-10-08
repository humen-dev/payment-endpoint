import uuid
from http import HTTPStatus

from flask import Blueprint, jsonify, request

from shop.auth import current_user_id
from shop.errors import BadRequest
from shop.models import IDEMPOTENCY_KEY_MAX_LENGTH, Payment, PaymentStatus
from shop.payments.service import start_payment

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

payments_blueprint = Blueprint("payments", __name__)


@payments_blueprint.post("/carts/<uuid:cart_id>/payments")
def create_payment(cart_id: uuid.UUID):
    payment = start_payment(
        user_id=current_user_id(),
        cart_id=cart_id,
        idempotency_key=_idempotency_key(),
        payment_method_id=_payment_method_id(),
    )
    status = (
        HTTPStatus.CREATED
        if payment.status == PaymentStatus.SUCCEEDED
        else HTTPStatus.PAYMENT_REQUIRED
    )
    return jsonify(_payment_to_json(payment)), status


def _idempotency_key() -> str:
    key = request.headers.get(IDEMPOTENCY_KEY_HEADER, "").strip()
    if not 0 < len(key) <= IDEMPOTENCY_KEY_MAX_LENGTH:
        raise BadRequest(
            "invalid_idempotency_key",
            f"Send the {IDEMPOTENCY_KEY_HEADER} header "
            f"(1 to {IDEMPOTENCY_KEY_MAX_LENGTH} characters).",
        )
    return key


def _payment_method_id() -> uuid.UUID | None:
    """Reads the optional payment method from the body.

    No body means the default method.
    """
    if not request.get_data():
        return None

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest("invalid_body", "The request body must be a JSON object.")

    raw_id = body.get("payment_method_id")
    if raw_id is None:
        return None
    try:
        return uuid.UUID(str(raw_id))
    except ValueError:
        raise BadRequest(
            "invalid_payment_method_id", "payment_method_id must be a UUID."
        )


def _payment_to_json(payment: Payment) -> dict:
    return {
        "id": str(payment.id),
        "cart_id": str(payment.cart_id),
        "payment_method_id": str(payment.payment_method_id),
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "provider_payment_id": payment.provider_payment_id,
        "failure_reason": payment.failure_reason,
    }
