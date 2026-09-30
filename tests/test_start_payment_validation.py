"""Requests that must be rejected before the payment provider is called."""
import uuid

import pytest

from shop.models import CartStatus, UserPaymentMethod
from shop.payments import provider


@pytest.fixture(autouse=True)
def provider_must_not_be_called(monkeypatch):
    def fail(**kwargs):
        pytest.fail("The payment provider must not be called for a rejected request.")

    monkeypatch.setattr(provider, "charge", fail)


@pytest.mark.parametrize("user_id", [None, "not-a-uuid", str(uuid.uuid4())])
def test_unknown_user_is_unauthorized(pay, cart, card, user_id):
    response = pay(cart.id, {"X-User-Id": user_id})

    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorized"


@pytest.mark.parametrize("key", [None, "", "   ", "k" * 256])
def test_invalid_idempotency_key_is_rejected(pay, cart, card, key):
    response = pay(cart.id, {"Idempotency-Key": key})

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_idempotency_key"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ([], "invalid_body"),
        ({"payment_method_id": "not-a-uuid"}, "invalid_payment_method_id"),
        ({"payment_method_id": 42}, "invalid_payment_method_id"),
    ],
)
def test_invalid_body_is_rejected(pay, cart, card, body, error):
    response = pay(cart.id, json=body)

    assert response.status_code == 400
    assert response.get_json()["error"] == error


def test_missing_cart_is_not_found(pay, card):
    response = pay(uuid.uuid4())

    assert response.status_code == 404
    assert response.get_json()["error"] == "cart_not_found"


def test_cart_of_another_user_is_not_found(pay, card, make_cart, other_user):
    response = pay(make_cart(other_user).id)

    assert response.status_code == 404
    assert response.get_json()["error"] == "cart_not_found"


def test_malformed_cart_id_is_not_found(pay):
    response = pay("not-a-uuid")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


@pytest.mark.parametrize("status", [CartStatus.CHECKED_OUT, CartStatus.ABANDONED])
def test_inactive_cart_cannot_be_paid(pay, cart, card, create, status):
    cart.status = status
    create(cart)

    response = pay(cart.id)

    assert response.status_code == 409
    assert response.get_json()["error"] == "cart_not_active"


def test_empty_cart_cannot_be_paid(pay, make_cart, user, card):
    response = pay(make_cart(user, prices=()).id)

    assert response.status_code == 422
    assert response.get_json()["error"] == "cart_empty"


def test_free_cart_cannot_be_paid(pay, make_cart, user, card):
    response = pay(make_cart(user, prices=("0.00",)).id)

    assert response.status_code == 422
    assert response.get_json()["error"] == "nothing_to_pay"


def test_cart_with_mixed_currencies_cannot_be_paid(pay, cart, card, create):
    cart.items[0].product.currency = "EUR"
    create(cart)

    response = pay(cart.id)

    assert response.status_code == 422
    assert response.get_json()["error"] == "mixed_currencies"


def test_user_without_default_payment_method_cannot_pay(pay, cart, declined_card):
    response = pay(cart.id)

    assert response.status_code == 422
    assert response.get_json()["error"] == "payment_method_not_found"


def test_payment_method_of_another_user_cannot_be_used(pay, cart, card, create, other_user):
    bobs_card = create(UserPaymentMethod(user_id=other_user.id, provider_token="tok_bob"))

    response = pay(cart.id, json={"payment_method_id": str(bobs_card.id)})

    assert response.status_code == 422
    assert response.get_json()["error"] == "payment_method_not_found"
