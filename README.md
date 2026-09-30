# Payment Endpoint

The payment part of an online shop: a PostgreSQL schema for payments and an HTTP endpoint
that starts the payment for a cart.

Stack: Python 3.12, Flask, SQLAlchemy 2, Alembic, PostgreSQL 16, pytest.

## Run

Requirements: Python 3.12+, Docker.

```bash
docker compose up -d --wait               # PostgreSQL on localhost:5434 (databases: shop, shop_test)
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head                      # base schema + sample data, then the payments table
flask --app wsgi run
```

Pay for the sample cart of Alice (70.00 USD):

```bash
curl -i -X POST http://127.0.0.1:5000/carts/c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1/payments \
  -H "X-User-Id: 11111111-1111-1111-1111-111111111111" \
  -H "Idempotency-Key: 5f0c2a4e-2b1d-4c1a-9a57-0a3f3b8e7d11"
```

The database URLs come from `DATABASE_URL` and `TEST_DATABASE_URL` (see `.env.example`).
The defaults match `docker-compose.yml`.

## Test

```bash
pytest
```

The tests use a real PostgreSQL database (`shop_test`), because the payment logic depends on
row locks and unique indexes. The test suite runs the migrations itself and empties the tables
before each test.

* `tests/test_start_payment.py` — requests that reach the provider: success, decline, provider
  errors, idempotency and parallel requests (two threads pay one cart; the card is charged once).
* `tests/test_start_payment_validation.py` — requests that must be rejected. In this module the
  provider mock fails the test if it is called, so every case also checks that no card is charged.
* `tests/test_provider.py` — the provider mock.

## API

### `POST /carts/<cart_id>/payments`

| Header            | Required | Description                                                     |
|-------------------|----------|-----------------------------------------------------------------|
| `X-User-Id`       | yes      | The current user (an authentication stub, see Assumptions).     |
| `Idempotency-Key` | yes      | 1–255 characters. One key per payment attempt, see Idempotency. |

Body (optional): `{"payment_method_id": "<uuid>"}`. Without it, the default payment method of
the user is charged.

Response — the payment:

```json
{
  "id": "c6a71fe5-77b5-4d83-ba3f-19f6aed7fbdc",
  "cart_id": "c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1",
  "payment_method_id": "11111111-2222-3333-4444-555555555555",
  "status": "succeeded",
  "amount": "70.00",
  "currency": "USD",
  "provider_payment_id": "pay_b68c1cf20f4f47c49534f3358620cf3d",
  "failure_reason": null
}
```

| Status | When                                                                                      |
|--------|-------------------------------------------------------------------------------------------|
| 201    | The card was charged. The cart is now `checked_out`.                                       |
| 402    | The provider declined the card. `status` is `failed`, the cart stays `active`.             |
| 400    | Missing or invalid `Idempotency-Key`, invalid body.                                       |
| 401    | Missing or invalid `X-User-Id`, unknown user.                                             |
| 404    | The cart does not exist or belongs to another user.                                       |
| 409    | The cart is not `active` (`cart_not_active`), or its payment is in progress (`payment_in_progress`). |
| 422    | Empty cart, zero total, mixed currencies, no payment method, key reused for another request. |
| 502    | The provider did not answer (`provider_unavailable`). The payment stays `pending`, see Assumptions. |

Errors have one format: `{"error": "cart_not_found", "message": "Cart not found."}`.

## Design

### Schema

`migrations/versions/0002_payments.py` adds the `payments` table. One row is one attempt to
charge a cart:

* `amount`, `currency` — a snapshot of the cart total at the moment of payment.
* `status` — `pending` → `succeeded` | `failed`.
* `payment_method_id` — the card that was charged; `provider_payment_id` / `failure_reason` —
  the provider answer.
* `idempotency_key` — unique per user (`uq_payments_user_idempotency_key`).
* `uq_payments_cart_active` — a partial unique index: at most one `pending` or `succeeded`
  payment per cart. Failed attempts do not block a new attempt.

The base schema from the task is applied unchanged by `0001_base_schema.py` from
`sql/base_schema.sql`.

### Payment flow (`shop/payments/service.py`)

1. **Transaction 1.** Lock the cart row (`SELECT ... FOR UPDATE`), so parallel requests for one
   cart run one after another. Check the idempotency key, validate the cart, pick the payment
   method, get the total, save a `pending` payment, commit.
2. **Provider call** outside of any transaction, so no lock or connection is held while waiting
   for the network.
3. **Transaction 2.** Save the result. On success, mark the cart `checked_out` in the same
   transaction.

### Idempotency

A client sends a new `Idempotency-Key` for each payment attempt and the same key when it retries
after a timeout or a lost connection.

* Same key, same request, finished payment → the stored result is returned (same status code
  and body). The card is not charged again.
* Same key while the first request is still running → `409 payment_in_progress`.
* Same key with another cart or another payment method → `422 idempotency_key_reused`. The
  server cannot tell whether the client wants a retry or a new payment, so it refuses rather
  than guess. A retry with another card is a new attempt and needs a new key.
* Different keys for one cart are still safe: `uq_payments_cart_active` allows only one
  pending/succeeded payment, and a paid cart is no longer `active`.
* The payment id is sent to the provider as its idempotency key, so a retry on the provider
  side cannot charge twice either.

## Assumptions

* **Authentication** is out of scope. The user id comes from the `X-User-Id` header. A real
  service would take it from a verified session or token.
* **Total calculation** already exists in the system. `shop/payments/totals.py` is a stand-in:
  the sum of `quantity × unit_price` of the cart items. It uses the prices stored on the cart
  items, not the current product prices, as the base schema intends. All products of a cart must
  have one currency.
* **Payment provider** is a mock (`shop/payments/provider.py`), driven by the card token:
  `tok_decline…` is declined with `card_declined`, `tok_unavailable…` raises
  `ProviderUnavailableError` (like a timeout), any other token is charged.
  The payment is synchronous: the endpoint returns the final result.
* **Decline and "no answer" are different.** A decline is a known result, so the payment is
  `failed` and the user can try again. When the provider does not answer, the card may have been
  charged, so the payment stays `pending` (response `502`) — marking it `failed` could lead to a
  second charge.
* **Default payment method.** The base schema allows several default methods per user; the newest
  one is used.
* **Stuck pending payments.** If the provider does not answer, or the process dies between the
  provider call and transaction 2, the payment stays `pending` and the cart cannot be paid again. In production a reconciliation
  job would fix such payments using the provider API or webhooks. It is not part of this task.
* **Idempotency keys** do not expire.
* **Out of scope:** stock reservation and decrement, orders and delivery, refunds,
  the `updated_at` columns of the base tables (they have no trigger; the app sets `updated_at`
  on the rows it changes).
* The sample data from the base schema stays in migration `0001` for manual checks.
