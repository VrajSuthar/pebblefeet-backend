# Pebble Feet Backend: What Was Built and How It Works

This guide explains everything added to the backend so it can run a real soap shop:
customers browse, add to cart, pay with **Razorpay** or **cash on delivery**, and you
manage orders from an admin panel.

- **67 API endpoints** (the full list is below; interactive docs at `http://localhost:8000/docs`)
- **35 automated tests**, all passing (`uv run pytest`)
- **Type-check clean** (Pyright: 0 errors, so no red lines in VS Code)
- **No database migration needed**: your existing tables already had every column required

---

## 1. Quick start

```bash
# 1. Install dependencies (pytest was added as a dev dependency)
uv sync

# 2. Create your admin account (uses DEFAULT_ADMIN_EMAIL / DEFAULT_ADMIN_PASSWORD from .env)
uv run python -m app.scripts.seed_admin

# 3. Run the server
uv run fastapi dev app/main.py

# 4. Run the tests (they use your local Postgres + Redis but change nothing; see section 9)
uv run pytest
```

Then open `http://localhost:8000/docs`, log in with `/auth/login`, click **Authorize**
and paste the `access_token`.

---

## 2. How the code is organised

Every feature follows the same 4 layers you already used for auth and products:

```
app/api/v1/endpoints/<feature>.py   → HTTP routes: read the request, call the service, wrap the reply
app/services/<feature>.py           → Business rules: "can this be cancelled?", "is stock enough?"
app/repository/<feature>.py         → Database queries only (SQLAlchemy)
app/schema/<feature>_schema.py      → Request/response shapes + validation (Pydantic)
```

Why: routes stay thin, rules live in one place, and tests can check the rules directly.

### Files added or changed

| Area | Files |
|---|---|
| Users & addresses | `endpoints/user.py`, `services/user.py`, `repository/user.py`, `schema/user_schema.py` |
| Cart | `endpoints/cart.py`, `services/cart.py`, `repository/cart.py`, `schema/cart_schema.py` |
| Wishlist | `endpoints/wishlist.py`, `services/wishlist.py`, `repository/wishlist.py`, `schema/wishlist_schema.py` |
| Orders & checkout | `endpoints/orders.py`, `services/order.py`, `services/order_view.py`, `repository/order.py`, `schema/order_schema.py` |
| Payments (Razorpay) | `endpoints/payment.py`, `services/payment.py`, `services/razorpay_client.py` |
| Money maths | `services/pricing.py` |
| Coupons | `services/coupon.py`, `repository/coupon.py`, `schema/coupon_schema.py` |
| Reviews | `endpoints/review.py`, `services/review.py`, `repository/review.py`, `schema/review_schema.py` |
| Admin panel API | `endpoints/admin.py`, `services/dashboard.py` |
| Health check | `endpoints/health.py` |
| Background job | `core/tasks.py` (cancels unpaid orders) |
| Shared helpers | `api/responses.py` (`ok`, `created`), `schema/common_schema.py` (pagination, PATCH helper), `repository/utils.py` (safe search) |
| Setup | `core/settings.py` (new settings), `core/application.py` (CORS, background job), `core/exception_handlers.py` |
| Admin seed | `scripts/seed_admin.py` |
| Tests | `tests/conftest.py`, `tests/fakes.py`, `tests/unit/*`, `tests/integration/*` |

Small changes to existing code:
- `auth.py` and `product.py` endpoints now use the shared `ok()`/`created()` helpers (same responses as before).
- Login now records `last_login_at` (the column existed but was never filled).
- `AuthRepository` got a public `invalidate_user()` so profile edits clear the Redis user cache.
- Products now show `rating_average` and `review_count`.

---

## 3. Every endpoint

🔓 = no login · 👤 = any logged-in user · 🛡️ = admin only

### Account
| Method | Path | Who | What it does |
|---|---|---|---|
| GET | `/health` | 🔓 | Returns 200 if Postgres and Redis are up (for hosting/uptime checks) |
| POST | `/auth/...` | 🔓/👤 | Sign-up, login, refresh, logout, forgot/reset/change password (unchanged) |
| GET | `/users/me` | 👤 | My profile |
| PATCH | `/users/me` | 👤 | Edit name / phone (phone must be unique) |
| POST | `/users/me/delete` | 👤 | Delete my account (asks for password, logs out every device) |
| GET / POST | `/users/me/addresses` | 👤 | List / add delivery addresses |
| GET / PATCH / DELETE | `/users/me/addresses/{id}` | 👤 | View / edit / remove an address |

### Shopping
| Method | Path | Who | What it does |
|---|---|---|---|
| GET | `/products`, `/products/{slug}`, `/products/categories` | 👤 | Browse the catalogue (unchanged, plus ratings) |
| GET | `/reviews/product/{product_id}` | 👤 | Reviews and the star summary (average, count, 5★…1★ bars) |
| POST | `/reviews` | 👤 | Write a review (one per product) |
| PATCH / DELETE | `/reviews/{id}` | 👤 | Edit / delete my review |
| GET / POST | `/wishlist` | 👤 | My wishlist / add a product |
| DELETE | `/wishlist/{product_id}` | 👤 | Remove from wishlist |
| GET | `/cart` | 👤 | My cart with totals and stock warnings |
| POST | `/cart/items` | 👤 | Add a variant (adding again increases the quantity) |
| PATCH / DELETE | `/cart/items/{id}` | 👤 | Change quantity / remove |
| DELETE | `/cart` | 👤 | Empty the cart |

### Checkout & orders
| Method | Path | Who | What it does |
|---|---|---|---|
| POST | `/orders/preview` | 👤 | Checkout totals with a coupon (reserves nothing) |
| POST | `/orders` | 👤 | **Place the order** from the cart |
| GET | `/orders` | 👤 | My orders (paginated, filter by status) |
| GET | `/orders/{id}` | 👤 | Order detail, tracking timeline and payments |
| POST | `/orders/{id}/pay` | 👤 | Retry payment for an unpaid order |
| POST | `/orders/{id}/cancel` | 👤 | Cancel (only before packing) |
| POST | `/orders/{id}/return` | 👤 | Request a return (within 7 days of delivery) |
| POST | `/payments/verify` | 👤 | Confirm a Razorpay payment from the app |
| POST | `/payments/webhook/razorpay` | 🔓* | Razorpay calls this; *protected by the signature, not a login |

### Admin panel
| Method | Path | What it does |
|---|---|---|
| GET | `/admin/dashboard` | Revenue today/30 days, orders by status, orders to ship, low stock, top products, customers |
| GET | `/admin/orders` | All orders: filter by status, payment, date; search order number, email or phone |
| GET | `/admin/orders/{id}` | Order with customer details |
| PATCH | `/admin/orders/{id}/status` | Move the order along (processing → shipped → delivered, cancel, mark returned) |
| GET / GET {id} / PATCH {id} | `/admin/users` | Find customers, block/unblock, change role |
| GET / POST / GET {id} / PATCH {id} / DELETE {id} | `/admin/coupons` | Manage coupon codes |
| GET / PATCH {id} | `/admin/reviews` | Find reviews, hide or restore them |
| | `/products/...` (POST/PATCH/DELETE) | Product, category, variant and image management (built earlier) |

Every response uses the same envelope:
```json
{ "status": "success", "status_code": 200, "message": "Order placed", "data": { ... }, "errors": null }
```
Errors (including validation errors, which used to come back in FastAPI's own format) now look the same:
```json
{ "status": "error", "status_code": 422, "message": "Enter a valid 6-digit PIN code",
  "errors": [{ "code": "VALIDATION_ERROR", "message": "Enter a valid 6-digit PIN code", "field": "postal_code" }] }
```
The `code` (like `COUPON_EXPIRED`, `CART_EMPTY` or `PAYMENT_SIGNATURE_INVALID`) is stable, so the app can show a specific screen for it.

---

## 4. The checkout and Razorpay flow

```
 Flutter app                         Your backend                         Razorpay
 ───────────                         ────────────                         ────────
 POST /orders/preview  ───────────▶  totals + coupon check
 POST /orders          ───────────▶  1. lock stock rows, check stock
                                     2. reserve stock, use coupon, empty cart
                                     3. save order (PENDING)
                                     4. create Razorpay order  ──────────▶ order_xxx
                       ◀───────────  data.payment = Checkout options
 open Razorpay Checkout ─────────────────────────────────────────────────▶ customer pays (UPI/card…)
                       ◀─────────────────────────────────────────────────  payment_id + signature
 POST /payments/verify ───────────▶  check signature, ask Razorpay
                                     "captured?", order → CONFIRMED
                                                          ◀──────────────  webhook payment.captured
                                     (same result, safe if it runs twice)
```

**Why both verify *and* webhook?** If the customer closes the app right after paying,
`/payments/verify` is never called. The webhook (server to server) still confirms the
order. Both paths are idempotent, so running twice changes nothing.

### What happens in the unusual cases

All of these are covered by automated tests except the two marked ⁽¹⁾.

| Situation | What the backend does |
|---|---|
| Payment fails (card declined) | Order stays PENDING and `payment_status` becomes `failed`. The app shows "Retry" (`can_pay: true`) and `POST /orders/{id}/pay` opens a fresh Checkout |
| Razorpay is down when placing the order | The order is still saved and stock reserved. The response has `payment_error`, and the app retries with `/orders/{id}/pay` |
| Customer never pays | After **30 minutes**, a background job cancels the order and returns the stock |
| Customer paid but both verify and the webhook were lost | Before cancelling, the job **asks Razorpay**. If the order was paid, it's confirmed instead |
| Customer pays *after* the order expired | The money is **refunded automatically** and the customer is told why |
| Customer pays twice ⁽¹⁾ | The second payment is refunded automatically |
| Someone sends a fake webhook | Rejected: the HMAC signature doesn't match |
| The same webhook arrives again (Razorpay retries) | Skipped using the event ID stored in Redis |
| Two people buy the last bar at the same moment ⁽¹⁾ | Stock rows are locked during checkout, so one succeeds and the other gets "Out of stock" |
| Cancelling a paid order / marking it returned | Full refund through the Razorpay API, stock added back, coupon use given back |

⁽¹⁾ Written and type-checked but not covered by a test: the double payment needs two real Razorpay
orders for one shop order, and a true race needs two parallel database connections, which the
rollback-based test setup can't do.

### Integrating in Flutter (`razorpay_flutter` package)

```dart
final res = await api.post('/orders', {'address_id': addressId, 'payment_method': 'razorpay'});
final p = res['data']['payment'];             // null for COD, or if payment_error is set

_razorpay.on(Razorpay.EVENT_PAYMENT_SUCCESS, (PaymentSuccessResponse r) async {
  await api.post('/payments/verify', {
    'razorpay_order_id': r.orderId,
    'razorpay_payment_id': r.paymentId,
    'razorpay_signature': r.signature,
  });                                          // returns the confirmed order
});
_razorpay.open({
  'key': p['key_id'],
  'order_id': p['razorpay_order_id'],
  'amount': p['amount'],                       // in paise
  'currency': p['currency'],
  'name': p['name'],
  'description': p['description'],
  'prefill': p['prefill'],
});
```
If verify returns `PAYMENT_PENDING`, show "Payment is processing". The webhook will confirm it shortly.

### Razorpay dashboard setup (one-time)

1. **API keys**: *Account & Settings → API Keys*. Put them in `.env` as `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`.
   Your `.env` already has **test** keys (`rzp_test_…`). Switch to live keys only at launch.
2. **Webhook**: *Account & Settings → Webhooks → Add new webhook*
   - URL: `https://<your-domain>/payments/webhook/razorpay` (it must be public HTTPS; for local testing use a tunnel such as ngrok)
   - Secret: any long random string, also saved in `.env` as `RAZORPAY_WEBHOOK_SECRET`
   - Events: `payment.captured`, `payment.failed`, `order.paid`, `refund.processed`
3. **Auto-capture**: keep *Payment Capture → Automatic* on (the default). The backend also captures
   "authorized" payments itself as a safety net, so nothing gets auto-refunded by Razorpay after 5 days.

> I could not test against Razorpay's real servers from here. The tests use an in-memory fake Razorpay
> that produces signatures exactly the way Razorpay does, so the real verification code is what's tested.
> Before launch, place one order with your test keys and pay with Razorpay's test UPI ID `success@razorpay`.

---

## 5. Business rules I chose (change them in `.env`)

| Rule | Default | Setting |
|---|---|---|
| Shipping fee | ₹50 | `SHIPPING_FEE` |
| Free shipping from | ₹499 (after discount) | `FREE_SHIPPING_THRESHOLD` |
| Cash on delivery | On, up to ₹5000 | `COD_ENABLED`, `COD_MAX_ORDER_AMOUNT` |
| Max quantity of one item | 10 | `MAX_QUANTITY_PER_ITEM` |
| Unpaid order expires after | 30 minutes | `PENDING_ORDER_TTL_MINUTES` |
| Return window | 7 days after delivery | `RETURN_WINDOW_DAYS` |
| Max different items in cart | 30 | `MAX_CART_LINES` in `services/cart.py` |

### Prices include GST (important)
Indian law requires the printed MRP to include all taxes, so your product prices are treated as
**GST-inclusive**. The customer pays exactly the price shown: `total = subtotal − discount + shipping`.
`tax_amount` is the GST **already inside** that price, worked out per item at each product's
`gst_rate`. That's what goes on the invoice. Nothing is added on top.

> ⚠️ Ask your CA two things: (1) whether GST applies to your shipping charge (it is not taxed in this
> code), and (2) your exact HSN code and rate (the default is 3401 at 18%).

### Order statuses and who can change them
```
pending ──(payment)──▶ confirmed ──▶ processing ──▶ shipped ──▶ out_for_delivery ──▶ delivered
   │                       │              │                                          │
   └──────── cancelled ◀───┴──────────────┘                          return_requested ◀┘ (customer)
                                                                        │         │
                                                         returned ◀─────┘         └─▶ delivered (return rejected)
```
- **Customer** can cancel while `pending` or `confirmed`, and request a return while `delivered` (within 7 days).
- **Admin** follows the arrows. `shipped` needs a courier name and tracking number. You can't skip steps.
- **COD** orders start as `confirmed`, and are marked **paid** when you set them to `delivered`.
- Returned **COD** orders can't be refunded automatically, so the timeline notes "refund the customer manually" (UPI or bank transfer).

### Coupons
- Percentage (optionally capped, e.g. "20% off up to ₹200") or flat (₹100 off). A flat discount never goes below ₹0.
- Minimum order amount, total-use limit, per-customer limit (default 1), start and end dates.
- Codes are stored in capitals; customers can type them in any case.
- A use is counted when the order is placed and **given back if the order is cancelled**.
- Two people can't both use the last remaining use at the same moment: the coupon row is locked during checkout.

### Deleting things never destroys history
Deleting a product, variant, category, coupon or user account **archives** it (`is_active = false`).
Orders keep a **snapshot** of the product name, price, GST and delivery address at purchase time,
so later edits never change an old order or invoice.

### Other details
- **Order numbers** look like `PF-20261103-K7Q2M9` (date in India time + 6 random characters).
  They're random rather than 0001, 0002… so competitors can't count your sales, and the letters
  skip 0/O and 1/I so they're easy to read out over the phone.
- **Reviews**: one per customer per product. A "Verified purchase" badge appears once they have a
  delivered order with that product. Hidden reviews don't count toward the rating. The reviewer's name
  is shown as "Priya S.", never the full name.
- **Addresses**: there is always exactly one default. Indian PIN codes are validated (6 digits, not starting with 0).
- **Blocking a user** logs them out of every device immediately.
- **Admins can't block or demote themselves**, so you can't lock yourself out.

---

## 6. Security measures

- **Access token on every router** (`dependencies=[Depends(get_current_user)]`) for users, products, reviews,
  wishlist, cart and orders, plus `require_admin` on `/admin`. A new endpoint added to those files is protected
  even if it doesn't ask for `user`. Only 8 endpoints are public on purpose: `/health`, sign-up, login,
  refresh, the 3 forgot/reset-password steps, and the Razorpay webhook (protected by its signature instead).
- **Webhook** checked with HMAC-SHA256 over the exact raw body. Signatures are compared in constant time.
- **Payment verify** checks the signature *and* asks Razorpay whether the money was really captured.
  Amounts are checked too: a webhook for the wrong amount is ignored and logged.
- **Ownership checks** everywhere: a customer gets 404 (not 403) for another person's order, address or
  cart item, so IDs can't be probed.
- **Search inputs are escaped**, so typing `%` or `_` can't turn a search into "match everything".
- **Errors in production** no longer send internal details (SQL, file paths) to the client. They're
  only logged. Outside production you still see them for debugging.
- **CORS** is configured from `CORS_ORIGINS`. Yours is `*` (any website). Before launch, change it to your
  real domain, e.g. `CORS_ORIGINS=https://pebblefeet.in,https://admin.pebblefeet.in`.

---

## 7. Background job

`app/core/tasks.py` runs inside the API every 5 minutes. It cancels Razorpay orders that stayed unpaid
for 30 minutes and puts their stock back, after first asking Razorpay whether they were actually paid.
It's safe to run several server instances at once: each order is claimed with `SKIP LOCKED`, so two
servers never process the same order.

---

## 8. Admin account

Sign-up always creates customers. To create the first admin:
```bash
uv run python -m app.scripts.seed_admin
```
It uses `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` from `.env`. Running it again on an existing
account just makes that account admin. After logging in, set your real phone number with `PATCH /users/me`.

---

## 9. Tests

```bash
uv run pytest            # 35 tests, about 7 seconds
```
| File | Covers |
|---|---|
| `tests/unit/test_pricing.py` | GST extraction, coupon caps, discount split across items, free shipping, paise conversion |
| `tests/unit/test_razorpay_signatures.py` | Checkout and webhook signature checks, including tampered bodies |
| `tests/integration/test_user_cart_wishlist.py` | Profile, addresses and default address, account deletion, cart limits and stock warnings, wishlist |
| `tests/integration/test_orders_payments.py` | COD and Razorpay checkout, coupons, stock reservation, verify, webhook, failed payment retry, gateway down, refunds, expiry job, late payment, admin fulfilment and returns |
| `tests/integration/test_reviews_admin.py` | Reviews, rating summary, verified badge, moderation, blocking users, coupon admin, health |
| `tests/integration/test_products.py` | Product CRUD (from earlier) |

**Your data is safe.** Each test runs inside a database transaction that is **rolled back** at the end,
and the Redis keys it creates are deleted. I checked after the runs: 0 test users, orders or products
were left in your database.

---

## 10. What's still missing (recommended next steps)

These are outside this change, roughly in order of importance for launch:

1. **A real email/SMS provider.** Order confirmations, shipping updates and password-reset OTPs are
   currently only **logged**, not sent. Wire a provider (e.g. Amazon SES, Resend, MSG91) into `EmailService._deliver`.
2. **Product image upload.** Images are currently saved as URLs. Your `.env` already has S3/MinIO settings,
   so the next step is an upload endpoint that gives the admin panel a pre-signed upload URL.
3. **GST invoice PDF** for each order. All the data (HSN, rates, per-item amounts, address) is already stored.
4. **Public browsing.** Product and review endpoints currently require login (as you asked earlier). Most
   shops let visitors browse first and log in at checkout. To allow that, remove
   `dependencies=[Depends(get_current_user)]` from the product and review routers.
5. **Rate limiting** on login, sign-up and forgot-password, to slow down password guessing and OTP spam.
6. **Courier integration** (e.g. Shiprocket) to create shipments and fill in tracking automatically.
7. **Guest checkout** and **stock alerts** ("notify me when back in stock").

I didn't make a git commit. All the changes are in your working tree for you to review.
