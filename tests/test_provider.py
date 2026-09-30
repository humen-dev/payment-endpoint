from decimal import Decimal

import pytest

from shop.payments import provider


def charge(token: str) -> provider.ChargeResult:
    return provider.charge(token=token, amount=Decimal("10.00"), currency="USD", idempotency_key="k")


def test_charges_regular_token():
    result = charge("tok_test_visa")

    assert result.succeeded
    assert result.provider_payment_id.startswith("pay_")
    assert result.failure_reason is None


def test_declines_token_with_decline_prefix():
    result = charge("tok_decline_visa")

    assert not result.succeeded
    assert result.provider_payment_id is None
    assert result.failure_reason == "card_declined"


def test_raises_for_token_with_unavailable_prefix():
    with pytest.raises(provider.ProviderUnavailableError):
        charge("tok_unavailable_visa")
