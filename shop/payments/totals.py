"""Adapter to the existing payment total calculation service.

The task says this service already exists, so here is only a minimal stand-in:
the sum of the item prices stored on the cart.
"""

from dataclasses import dataclass
from decimal import Decimal

from shop.errors import Unprocessable
from shop.models import Cart


@dataclass(frozen=True)
class CartTotal:
    amount: Decimal
    currency: str


def calculate_cart_total(cart: Cart) -> CartTotal:
    currencies = {item.product.currency for item in cart.items}
    if len(currencies) != 1:
        raise Unprocessable(
            "mixed_currencies", "All products in the cart must have one currency."
        )

    amount = sum((item.unit_price * item.quantity for item in cart.items), Decimal("0"))
    return CartTotal(amount=amount, currency=currencies.pop())
