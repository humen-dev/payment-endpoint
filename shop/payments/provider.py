"""Mock of the external payment provider.

The mock is deterministic so that tests and manual checks are predictable:
* a token that starts with DECLINED_TOKEN_PREFIX is declined;
* a token that starts with UNAVAILABLE_TOKEN_PREFIX raises ProviderUnavailableError;
* any other token is charged.
"""
import uuid
from dataclasses import dataclass
from decimal import Decimal

DECLINED_TOKEN_PREFIX = "tok_decline"
UNAVAILABLE_TOKEN_PREFIX = "tok_unavailable"


class ProviderUnavailableError(Exception):
    """The provider did not answer (timeout, network error): the card may or may not be charged."""


@dataclass(frozen=True)
class ChargeResult:
    succeeded: bool
    provider_payment_id: str | None = None
    failure_reason: str | None = None


def charge(token: str, amount: Decimal, currency: str, idempotency_key: str) -> ChargeResult:
    """Charges the card behind `token`.

    A real provider uses `idempotency_key` to return the first result for a repeated
    request instead of charging the card twice.
    """
    if token.startswith(UNAVAILABLE_TOKEN_PREFIX):
        raise ProviderUnavailableError("The payment provider did not answer.")
    if token.startswith(DECLINED_TOKEN_PREFIX):
        return ChargeResult(succeeded=False, failure_reason="card_declined")
    return ChargeResult(succeeded=True, provider_payment_id=f"pay_{uuid.uuid4().hex}")
