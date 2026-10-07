"""Tests run against a real PostgreSQL database (`TestConfig`), migrated with Alembic.

Test data is written and checked through a separate SQLAlchemy session, like an outside
observer, so the app's own session state never leaks into the assertions.
"""

from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from shop import create_app
from shop.config import TestConfig
from shop.models import Cart, CartItem, Product, User, UserPaymentMethod

DATABASE_URL = TestConfig.SQLALCHEMY_DATABASE_URI


@pytest.fixture(scope="session")
def alembic_config():
    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


@pytest.fixture(scope="session")
def engine(alembic_config):
    command.upgrade(alembic_config, "head")

    engine = create_engine(DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE payments, user_payment_methods, cart_items, carts, "
                "products, users"
            )
        )


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="session")
def app():
    return create_app(TestConfig)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def create(session):
    """Saves a model and returns it."""

    def _create(model):
        session.add(model)
        session.commit()
        return model

    return _create


@pytest.fixture
def reload(session):
    """Returns the current database state of a model."""

    def _reload(model):
        session.refresh(model)
        return model

    return _reload


@pytest.fixture
def user(create):
    return create(User(email="alice@example.com", name="Alice"))


@pytest.fixture
def other_user(create):
    return create(User(email="bob@example.com", name="Bob"))


@pytest.fixture
def card(create, user):
    return create(
        UserPaymentMethod(
            user_id=user.id,
            provider_token="tok_test_visa",
            last_four="4242",
            is_default=True,
        )
    )


@pytest.fixture
def declined_card(create, user):
    return create(
        UserPaymentMethod(
            user_id=user.id, provider_token="tok_decline_visa", last_four="0002"
        )
    )


@pytest.fixture
def make_cart(create):
    def _make_cart(
        owner: User, prices: tuple[str, ...] = ("45.00", "12.50", "12.50")
    ) -> Cart:
        items = [
            CartItem(
                product=Product(name=f"Product {price}", price=Decimal(price)),
                quantity=1,
                unit_price=Decimal(price),
            )
            for price in prices
        ]
        return create(Cart(user_id=owner.id, items=items))

    return _make_cart


@pytest.fixture
def cart(make_cart, user):
    """A cart of 70.00 USD."""
    return make_cart(user)


@pytest.fixture
def pay(client, user):
    """Sends the payment request as `user`. A header set to `None` is left out."""

    def _pay(cart_id, headers=None, json=None):
        headers = {
            "X-User-Id": str(user.id),
            "Idempotency-Key": "key-1",
            **(headers or {}),
        }
        headers = {name: value for name, value in headers.items() if value is not None}
        return client.post(f"/carts/{cart_id}/payments", headers=headers, json=json)

    return _pay
