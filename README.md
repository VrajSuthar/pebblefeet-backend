# Pebble Feet Backend

The REST API behind **Pebble Feet**, an online soap shop. It powers the Flutter app and the admin
panel: customers browse products, manage a cart and wishlist, check out with **Razorpay** or
**cash on delivery**, and track their orders. Admins manage products, orders, coupons, reviews and
customers.

> For the full write-up (every endpoint, the checkout flow, business rules and edge cases), see
> [BACKEND_GUIDE.md](BACKEND_GUIDE.md).

## Features

- **Auth**: sign-up, login, JWT access + refresh tokens, logout, forgot / reset / change password
- **Users**: profile, multiple delivery addresses with a default, account deletion
- **Catalogue**: products, variants, categories, images, ratings
- **Cart & wishlist**: stock warnings, quantity limits
- **Orders**: checkout preview, coupons, GST-inclusive pricing, cancel, returns, tracking timeline
- **Payments**: Razorpay Checkout, signature verification, webhooks, automatic refunds, COD
- **Reviews**: one per product, "verified purchase" badge, admin moderation
- **Admin panel API**: dashboard stats, order fulfilment, customer management, coupons
- **Background job**: cancels unpaid orders after 30 minutes and returns their stock
- **Health check** at `/health` for hosting and uptime monitoring

## Tech stack

| | |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI |
| Database | PostgreSQL (SQLAlchemy 2 async + asyncpg) |
| Migrations | Alembic |
| Cache / sessions | Redis |
| Payments | Razorpay |
| Auth | JWT (PyJWT) + bcrypt |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Tests | pytest + pytest-asyncio |

## Getting started

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- PostgreSQL and Redis running locally

### Setup

```bash
# 1. Clone and install dependencies
git clone https://github.com/VrajSuthar/pebblefeet-backend.git
cd pebblefeet-backend
uv sync

# 2. Create your environment file and fill in the values
cp .env.example .env

# 3. Create the database tables
uv run alembic upgrade head

# 4. Create the first admin account (uses DEFAULT_ADMIN_EMAIL / DEFAULT_ADMIN_PASSWORD)
uv run python -m app.scripts.seed_admin

# 5. Start the development server
uv run fastapi dev app/main.py
```

The API runs at `http://localhost:8000`. Interactive docs are at
[`/docs`](http://localhost:8000/docs) (Swagger) and [`/redoc`](http://localhost:8000/redoc).
To call protected endpoints from Swagger, log in with `POST /auth/login`, click **Authorize** and
paste the `access_token`.

## Configuration

All settings are read from `.env`. See [.env.example](.env.example) for the full list.

| Variable | Purpose |
|---|---|
| `ENVIRONMENT`, `DEBUG` | `development` / `production`. Production hides internal error details |
| `SECRET_KEY` | Signs JWTs. **Use a long random value** |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | Token lifetimes |
| `DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis connection string |
| `CORS_ORIGINS` | Comma-separated allowed origins (your website / admin panel) |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay API keys (use `rzp_test_` keys until launch) |
| `RAZORPAY_WEBHOOK_SECRET` | Secret set on the Razorpay webhook |
| `SHIPPING_FEE`, `FREE_SHIPPING_THRESHOLD` | Shipping rules (defaults ₹50, free from ₹499) |
| `COD_ENABLED`, `COD_MAX_ORDER_AMOUNT` | Cash on delivery rules |
| `MAX_QUANTITY_PER_ITEM` | Max quantity of one item per order |
| `PENDING_ORDER_TTL_MINUTES` | How long an unpaid order is held before it's cancelled |
| `RETURN_WINDOW_DAYS` | Days after delivery a customer can request a return |
| `DEFAULT_ADMIN_EMAIL`, `DEFAULT_ADMIN_PASSWORD` | Used by the admin seed script |

Never commit `.env`; it is already in `.gitignore`.

## Project structure

```
app/
├── api/v1/endpoints/   # HTTP routes: read the request, call a service, return the response
├── services/           # Business rules (pricing, checkout, payments, coupons, ...)
├── repository/         # Database queries (SQLAlchemy)
├── schema/             # Request / response models and validation (Pydantic)
├── model/              # SQLAlchemy ORM models
├── core/               # Settings, security, logging, exception handlers, background tasks
├── database/           # PostgreSQL session and Redis client
├── middleware/         # Request logging
├── scripts/            # One-off scripts (seed_admin)
└── main.py             # App entry point
migrations/             # Alembic migrations
tests/
├── unit/               # Pricing and Razorpay signature tests
└── integration/        # End-to-end API tests
```

Each feature follows the same layers: **endpoint → service → repository**, with schemas for
input/output.

## API overview

| Prefix | Who | What |
|---|---|---|
| `/health` | Public | Postgres + Redis status |
| `/auth` | Public / user | Sign-up, login, refresh, logout, password reset and change |
| `/users/me` | User | Profile and addresses |
| `/products` | User (writes: admin) | Catalogue, categories, variants, images |
| `/reviews` | User | Product reviews and rating summary |
| `/wishlist` | User | Saved products |
| `/cart` | User | Cart items and totals |
| `/orders` | User | Checkout preview, place order, history, pay, cancel, return |
| `/payments` | User / Razorpay | Payment verification and the Razorpay webhook |
| `/admin` | Admin | Dashboard, orders, users, coupons, review moderation |

Every response uses the same envelope:

```json
{ "status": "success", "status_code": 200, "message": "Order placed", "data": { }, "errors": null }
```

Errors include a stable `code` (for example `CART_EMPTY`, `COUPON_EXPIRED`,
`PAYMENT_SIGNATURE_INVALID`) that the app can react to.

## Razorpay setup

1. Add your API keys from *Razorpay Dashboard → Account & Settings → API Keys* to `.env`.
2. Create a webhook at *Account & Settings → Webhooks*:
   - URL: `https://<your-domain>/payments/webhook/razorpay` (use a tunnel such as ngrok locally)
   - Secret: a long random string, also saved as `RAZORPAY_WEBHOOK_SECRET`
   - Events: `payment.captured`, `payment.failed`, `order.paid`, `refund.processed`
3. Test a payment with test keys and the UPI ID `success@razorpay`.

See [BACKEND_GUIDE.md](BACKEND_GUIDE.md#4-the-checkout-and-razorpay-flow) for the full payment
flow and Flutter integration example.

## Database migrations

```bash
uv run alembic upgrade head                             # apply all migrations
uv run alembic revision --autogenerate -m "describe"    # create a migration after changing models
uv run alembic downgrade -1                             # roll back the last migration
```

## Running tests

```bash
uv run pytest
```

The integration tests use your local PostgreSQL and Redis, but each test runs inside a
transaction that is rolled back, and the Redis keys it creates are deleted, so your data is
left unchanged.

## Before going to production

- Set `ENVIRONMENT=production` and `DEBUG=false`
- Use a strong, unique `SECRET_KEY`
- Restrict `CORS_ORIGINS` to your real domains
- Switch to live Razorpay keys and update the webhook URL
- Connect a real email/SMS provider (emails are only logged for now)

## Author

[Vraj Suthar](https://github.com/VrajSuthar)
