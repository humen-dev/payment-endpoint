"""Payments that reach the provider.

Covers success, decline, provider errors, idempotency and concurrency.
Requests rejected before the provider call: `test_start_payment_validation.py`.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from shop.models import CartStatus, Payment, PaymentStatus, UserPaymentMethod
from shop.payments import provider


@pytest.fixture
def provider_calls(monkeypatch):
    """Records every call to the payment provider and passes it on to the mock."""
    calls = []
    real_charge = provider.charge

    def recording_charge(**kwargs):
        calls.append(kwargs)
        return real_charge(**kwargs)

    monkeypatch.setattr(provider, "charge", recording_charge)
    return calls


@pytest.fixture
def slow_provider(monkeypatch, provider_calls):
    """Makes the provider call slow, so parallel requests overlap.

    Calls are still recorded.
    """
    recording_charge = provider.charge

    def slow_charge(**kwargs):
        time.sleep(0.3)
        return recording_charge(**kwargs)

    monkeypatch.setattr(provider, "charge", slow_charge)


@pytest.fixture
def unavailable_card(create, user):
    return create(
        UserPaymentMethod(
            user_id=user.id, provider_token="tok_unavailable_visa", is_default=True
        )
    )


def count_payments(session) -> int:
    return session.scalar(select(func.count()).select_from(Payment))


def pending_payment(cart, payment_method, idempotency_key) -> Payment:
    return Payment(
        cart_id=cart.id,
        user_id=cart.user_id,
        payment_method_id=payment_method.id,
        amount=Decimal("70.00"),
        currency="USD",
        idempotency_key=idempotency_key,
    )


# --- Successful and declined payments -------------------------------------------------


def test_pays_cart_with_default_card(pay, cart, card, session, reload, provider_calls):
    response = pay(cart.id)

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "succeeded"
    assert body["amount"] == "70.00"
    assert body["currency"] == "USD"
    assert body["payment_method_id"] == str(card.id)
    assert body["provider_payment_id"].startswith("pay_")
    assert body["failure_reason"] is None

    payment = session.get(Payment, uuid.UUID(body["id"]))
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.amount == Decimal("70.00")
    assert payment.idempotency_key == "key-1"
    assert reload(cart).status == CartStatus.CHECKED_OUT

    assert provider_calls == [
        {
            "token": "tok_test_visa",
            "amount": Decimal("70.00"),
            "currency": "USD",
            "idempotency_key": body["id"],
        }
    ]


def test_amount_uses_prices_stored_in_cart_not_current_product_prices(
    pay, cart, card, create
):
    for item in cart.items:
        item.product.price += Decimal("100.00")
    create(cart)

    response = pay(cart.id)

    assert response.status_code == 201
    assert response.get_json()["amount"] == "70.00"


def test_pays_with_requested_payment_method(pay, cart, card, create, user):
    other_card = create(
        UserPaymentMethod(user_id=user.id, provider_token="tok_test_mastercard")
    )

    response = pay(cart.id, json={"payment_method_id": str(other_card.id)})

    assert response.status_code == 201
    assert response.get_json()["payment_method_id"] == str(other_card.id)


def test_declined_card_fails_payment_and_keeps_cart_active(
    pay, cart, card, declined_card, session, reload
):
    response = pay(cart.id, json={"payment_method_id": str(declined_card.id)})

    assert response.status_code == 402
    body = response.get_json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "card_declined"
    assert body["provider_payment_id"] is None
    assert session.get(Payment, uuid.UUID(body["id"])).status == PaymentStatus.FAILED
    assert reload(cart).status == CartStatus.ACTIVE


def test_cart_can_be_paid_with_new_key_after_decline(
    pay, cart, card, declined_card, reload
):
    pay(
        cart.id,
        {"Idempotency-Key": "attempt-1"},
        {"payment_method_id": str(declined_card.id)},
    )

    response = pay(cart.id, {"Idempotency-Key": "attempt-2"})

    assert response.status_code == 201
    assert reload(cart).status == CartStatus.CHECKED_OUT


# --- Provider does not answer ---------------------------------------------------------


def test_provider_error_keeps_payment_pending(
    pay, cart, unavailable_card, session, reload
):
    response = pay(cart.id)

    assert response.status_code == 502
    assert response.get_json()["error"] == "provider_unavailable"
    payment = session.scalars(select(Payment)).one()
    assert payment.status == PaymentStatus.PENDING
    assert str(payment.id) in response.get_json()["message"]
    assert reload(cart).status == CartStatus.ACTIVE


def test_retry_after_provider_error_does_not_charge_again(
    pay, cart, unavailable_card, provider_calls
):
    pay(cart.id)

    response = pay(cart.id)

    assert response.status_code == 409
    assert response.get_json()["error"] == "payment_in_progress"
    assert len(provider_calls) == 1


# --- Idempotency ----------------------------------------------------------------------


def test_repeated_request_returns_first_result_without_second_charge(
    pay, cart, card, session, provider_calls
):
    first = pay(cart.id)
    repeated = pay(cart.id)

    assert repeated.status_code == 201
    assert repeated.get_json() == first.get_json()
    assert len(provider_calls) == 1
    assert count_payments(session) == 1


def test_repeated_request_with_explicit_default_method_is_same_request(pay, cart, card):
    first = pay(cart.id)
    repeated = pay(cart.id, json={"payment_method_id": str(card.id)})

    assert repeated.status_code == 201
    assert repeated.get_json()["id"] == first.get_json()["id"]


def test_repeated_declined_request_returns_same_failure(
    pay, cart, card, declined_card, provider_calls
):
    body = {"payment_method_id": str(declined_card.id)}
    first = pay(cart.id, json=body)
    repeated = pay(cart.id, json=body)

    assert repeated.status_code == 402
    assert repeated.get_json() == first.get_json()
    assert len(provider_calls) == 1


def test_key_reused_for_another_cart_is_rejected(
    pay, make_cart, user, card, provider_calls
):
    pay(make_cart(user).id)

    response = pay(make_cart(user).id)

    assert response.status_code == 422
    assert response.get_json()["error"] == "idempotency_key_reused"
    assert len(provider_calls) == 1


def test_key_reused_with_another_payment_method_is_rejected(
    pay, cart, card, declined_card, provider_calls
):
    pay(cart.id, json={"payment_method_id": str(declined_card.id)})

    response = pay(cart.id, json={"payment_method_id": str(card.id)})

    assert response.status_code == 422
    assert response.get_json()["error"] == "idempotency_key_reused"
    assert len(provider_calls) == 1


def test_same_key_of_different_users_does_not_conflict(
    pay, cart, card, make_cart, other_user, create
):
    create(
        UserPaymentMethod(
            user_id=other_user.id, provider_token="tok_bob", is_default=True
        )
    )
    pay(cart.id)

    response = pay(make_cart(other_user).id, {"X-User-Id": str(other_user.id)})

    assert response.status_code == 201


def test_request_with_key_of_pending_payment_is_in_progress(
    pay, cart, card, create, provider_calls
):
    create(pending_payment(cart, card, idempotency_key="key-1"))

    response = pay(cart.id)

    assert response.status_code == 409
    assert response.get_json()["error"] == "payment_in_progress"
    assert provider_calls == []


def test_new_key_while_cart_payment_is_pending_is_in_progress(
    pay, cart, card, create, session, provider_calls
):
    create(pending_payment(cart, card, idempotency_key="other-key"))

    response = pay(cart.id)

    assert response.status_code == 409
    assert response.get_json()["error"] == "payment_in_progress"
    assert provider_calls == []
    assert count_payments(session) == 1


def test_new_key_for_paid_cart_is_rejected(pay, cart, card, session, provider_calls):
    pay(cart.id, {"Idempotency-Key": "attempt-1"})

    response = pay(cart.id, {"Idempotency-Key": "attempt-2"})

    assert response.status_code == 409
    assert response.get_json()["error"] == "cart_not_active"
    assert len(provider_calls) == 1
    assert count_payments(session) == 1


# --- Concurrency ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "keys", [("key-1", "key-1"), ("key-1", "key-2")], ids=["same-key", "different-keys"]
)
def test_parallel_requests_charge_cart_once(
    app, user, cart, card, session, slow_provider, provider_calls, keys
):
    def send(key):
        headers = {"X-User-Id": str(user.id), "Idempotency-Key": key}
        return (
            app.test_client()
            .post(f"/carts/{cart.id}/payments", headers=headers)
            .status_code
        )

    with ThreadPoolExecutor(max_workers=len(keys)) as executor:
        status_codes = sorted(executor.map(send, keys))

    assert status_codes == [201, 409]
    assert len(provider_calls) == 1
    assert count_payments(session) == 1
