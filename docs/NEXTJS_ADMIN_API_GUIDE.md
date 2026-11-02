# Connecting the Next.js Admin Panel to the Pebble Feet API

This guide shows how the admin panel (Next.js App Router + TypeScript) talks to this backend:
admin login, dashboard, orders and shipping, products and stock, categories, customers, coupons
and review moderation.

It builds on the website guide, [NEXTJS_WEBSITE_API_GUIDE.md](NEXTJS_WEBSITE_API_GUIDE.md).
Read sections 1 and 2 there first: the response format, the token rules and the overall setup are the same.

---

## 1. What's different for the admin panel

| | Website | Admin panel |
|---|---|---|
| Who logs in | Customers | Users with `role: "admin"` only |
| Sign-up | Yes | **No**. Create admins with the seed script or promote a user |
| Endpoints | `/products`, `/cart`, `/orders`, ... | `/admin/*` plus the admin-only product routes |
| Cookie names | `pf_*` | `pfa_*`, so both apps can run on the same domain without clashing |
| Pages open without login | Login, sign-up, forgot password | Login only |

The backend checks the role on every admin request (403 `FORBIDDEN` for customers), so the
panel's own role check is for a good experience, not for security.

### Creating the first admin

```bash
# In the backend folder. Uses DEFAULT_ADMIN_EMAIL / DEFAULT_ADMIN_PASSWORD from .env
uv run python -m app.scripts.seed_admin
```

After that, an admin can promote other users from the panel with `PATCH /admin/users/{id}` and `{ "role": "admin" }`.

---

## 2. Setup

`.env.local`:

```bash
API_URL=http://localhost:8000
```

### Files

```
proxy.ts                               # token refresh + login redirect   (changed: see below)
lib/
├── errors.ts                          # same as the website guide
├── backend.ts                         # same as the website guide
├── api.ts                             # same as the website guide
├── client-api.ts                      # same as the website guide
├── auth-helpers.ts                    # same as the website guide
├── session.ts                         # changed: cookie names
└── types.ts                           # admin types (below)
app/api/
├── auth/login/route.ts                # changed: admin role check
├── auth/logout/route.ts               # same as the website guide
└── backend/[...path]/route.ts         # same as the website guide
```

Copy the files marked "same" from section 4 of the website guide. Only the changes are shown here.
There is no sign-up route in the admin panel.

### `lib/session.ts`: different cookie names

Change only the four names; the rest of the file is identical:

```ts
export const ACCESS_COOKIE = "pfa_access";
export const REFRESH_COOKIE = "pfa_refresh";
export const EXPIRES_AT_COOKIE = "pfa_access_expires_at";
export const DEVICE_COOKIE = "pfa_device";
```

### `app/api/auth/login/route.ts`: admins only

The login response doesn't include the role, so ask `/users/me` with the new token and refuse non-admins.

```ts
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { deviceInfo, errorJson, rememberDevice } from "@/lib/auth-helpers";
import { setSession } from "@/lib/session";
import type { AuthResponse, Profile } from "@/lib/types";

export async function POST(req: NextRequest) {
  const { email, password } = await req.json();
  const device = deviceInfo(req);
  try {
    const data = await backendFetch<AuthResponse>("/auth/login", {
      method: "POST",
      body: { email, password, device_name: `Admin ${device.device_name}`.slice(0, 100), player_id: device.player_id },
    });
    const me = await backendFetch<Profile>("/users/me", { token: data.access_token });

    if (me.role !== "admin") {
      // Don't leave a live session behind for a customer account
      await backendFetch("/auth/logout", {
        method: "POST",
        token: data.access_token,
        body: { refresh_token: data.refresh_token },
      }).catch(() => {});
      return NextResponse.json({ status: "error", message: "This account is not an admin" }, { status: 403 });
    }

    const res = NextResponse.json({ status: "success", data: { user: me } });
    setSession(res.cookies, data);
    rememberDevice(res, device.player_id);
    return res;
  } catch (error) {
    return errorJson(error);
  }
}
```

### `proxy.ts`: only the login page is public

Use the website's `proxy.ts` and change the public list:

```ts
const PUBLIC_PAGES = ["/login"];
```

If an admin is demoted or blocked while logged in, the next request returns 403 or 401. Send them to
`/login` in both cases. In `lib/client-api.ts` change the redirect check to:

```ts
if (res.status === 401 || res.status === 403) {
  window.location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
}
```

and in `lib/api.ts`:

```ts
if (error instanceof ApiError && (error.status === 401 || error.status === 403)) redirect("/login");
```

> Only do the 403 redirect in the admin panel. A 403 there always means "not an admin any more".

---

## 3. Types

Add these to the website's `lib/types.ts` (copy that file first; the admin panel uses `Order`, `Page`,
`Money`, `ProductDetail`, `Category`, `Variant`, `Review` and others from it).

```ts
export type DashboardStats = {
  revenue_today: Money;
  revenue_last_30_days: Money;
  orders_today: number;
  orders_last_30_days: number;
  orders_to_fulfil: number;          // paid/confirmed orders waiting to be packed or shipped
  return_requests: number;
  orders_by_status: Partial<Record<OrderStatus, number>>;
  total_customers: number;
  new_customers_last_30_days: number;
  low_stock: { variant_id: string; product_name: string; variant_name: string; sku: string; stock: number }[];
  top_products_last_30_days: { product_name: string; quantity_sold: number; revenue: Money }[];
};

export type AdminOrder = Order & {
  customer: { id: string; first_name: string; last_name: string; email: string; phone_number: string };
};

export type AdminOrderListItem = OrderListItem & { customer_name: string; customer_email: string };

export type AdminUser = Profile & { is_active: boolean; last_login_at: string | null };

export type Coupon = {
  id: string;
  code: string;
  description: string | null;
  discount_type: "percentage" | "flat";
  discount_value: Money;
  max_discount_amount: Money | null;
  min_order_amount: Money;
  usage_limit: number | null;      // null = unlimited
  per_user_limit: number | null;   // null = unlimited
  used_count: number;
  valid_from: string;
  valid_until: string | null;
  is_active: boolean;
};
```

---

## 4. Pages

### Admin login

Same as the website's login page; it posts to `/api/auth/login`. Show the 403 message
"This account is not an admin" when a customer tries to log in.

### Dashboard

```tsx
// app/(admin)/page.tsx
import { api } from "@/lib/api";
import type { DashboardStats } from "@/lib/types";

const inr = (v: string) => `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

export default async function Dashboard() {
  const d = await api<DashboardStats>("/admin/dashboard");
  return (
    <main>
      <section>
        <div>Revenue today <strong>{inr(d.revenue_today)}</strong></div>
        <div>Revenue (30 days) <strong>{inr(d.revenue_last_30_days)}</strong></div>
        <div>Orders today <strong>{d.orders_today}</strong></div>
        <div>To ship <strong>{d.orders_to_fulfil}</strong></div>
        <div>Return requests <strong>{d.return_requests}</strong></div>
        <div>Customers <strong>{d.total_customers}</strong> (+{d.new_customers_last_30_days} in 30 days)</div>
      </section>

      <h2>Low stock</h2>
      <table>
        <tbody>
          {d.low_stock.map((v) => (
            <tr key={v.variant_id}><td>{v.product_name}</td><td>{v.variant_name}</td><td>{v.sku}</td><td>{v.stock}</td></tr>
          ))}
        </tbody>
      </table>

      <h2>Top products (30 days)</h2>
      <ol>
        {d.top_products_last_30_days.map((p) => (
          <li key={p.product_name}>{p.product_name}: {p.quantity_sold} sold, {inr(p.revenue)}</li>
        ))}
      </ol>
    </main>
  );
}
```

### Orders list with filters

```tsx
// app/(admin)/orders/page.tsx
import Link from "next/link";
import { api } from "@/lib/api";
import type { AdminOrderListItem, Page } from "@/lib/types";

type Filters = {
  page?: string; status?: string; payment_status?: string; payment_method?: string;
  q?: string; from?: string; to?: string;
};

export default async function OrdersPage({ searchParams }: { searchParams: Promise<Filters> }) {
  const f = await searchParams;
  const orders = await api<Page<AdminOrderListItem>>("/admin/orders", {
    query: {
      page: f.page ?? 1,
      page_size: 50,
      status: f.status,                 // pending | confirmed | processing | shipped | ...
      payment_status: f.payment_status, // pending | paid | failed | refunded | partially_refunded
      payment_method: f.payment_method, // razorpay | cod
      search: f.q,                      // order number, customer email or phone
      date_from: f.from,                // YYYY-MM-DD
      date_to: f.to,
    },
  });

  return (
    <main>
      <form>
        <input name="q" defaultValue={f.q} placeholder="Order no, email or phone" />
        <select name="status" defaultValue={f.status ?? ""}>
          <option value="">All statuses</option>
          <option value="confirmed">To pack (confirmed)</option>
          <option value="processing">Packing</option>
          <option value="shipped">Shipped</option>
          <option value="return_requested">Return requested</option>
        </select>
        <input type="date" name="from" defaultValue={f.from} />
        <input type="date" name="to" defaultValue={f.to} />
        <button>Filter</button>
      </form>

      <table>
        <tbody>
          {orders.items.map((o) => (
            <tr key={o.id}>
              <td><Link href={`/orders/${o.id}`}>{o.order_number}</Link></td>
              <td>{o.customer_name}<br /><small>{o.customer_email}</small></td>
              <td>{o.status}</td>
              <td>{o.payment_method} · {o.payment_status}</td>
              <td>₹{o.total_amount}</td>
              <td>{new Date(o.created_at).toLocaleString("en-IN")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>{orders.total} orders</p>
    </main>
  );
}
```

A plain `<form>` with GET puts the filters in the URL, so the server component re-renders with them
and filtered views can be bookmarked.

### Order detail and status updates

`GET /admin/orders/{id}` returns the full order plus `customer`. Change the status with
`PATCH /admin/orders/{id}/status`.

The backend only allows these moves; anything else returns 400 `INVALID_STATUS_TRANSITION`:

| From | Allowed next statuses |
|---|---|
| `pending` | `cancelled` |
| `confirmed` | `processing`, `cancelled` |
| `processing` | `shipped`, `cancelled` |
| `shipped` | `out_for_delivery`, `delivered` |
| `out_for_delivery` | `delivered` |
| `delivered` | `returned` |
| `return_requested` | `returned` (accept), `delivered` (reject the return) |
| `cancelled`, `returned` | none |

Put the same table in the panel so it only shows valid buttons:

```tsx
// app/(admin)/orders/[id]/status-actions.tsx
"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";
import { ApiError } from "@/lib/errors";
import type { AdminOrder, OrderStatus } from "@/lib/types";

const NEXT: Record<OrderStatus, OrderStatus[]> = {
  pending: ["cancelled"],
  confirmed: ["processing", "cancelled"],
  processing: ["shipped", "cancelled"],
  shipped: ["out_for_delivery", "delivered"],
  out_for_delivery: ["delivered"],
  delivered: ["returned"],
  return_requested: ["returned", "delivered"],
  cancelled: [],
  returned: [],
};

export function StatusActions({ order }: { order: AdminOrder }) {
  const router = useRouter();
  const [courier, setCourier] = useState(order.courier_name ?? "");
  const [tracking, setTracking] = useState(order.tracking_number ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  async function move(status: OrderStatus) {
    if (status === "cancelled" && !confirm(`Cancel ${order.order_number}? Paid orders are refunded.`)) return;
    try {
      await clientApi<AdminOrder>(`/admin/orders/${order.id}/status`, {
        method: "PATCH",
        body: {
          status,
          note: note || null,                 // shown in the customer's timeline
          courier_name: courier || null,      // required for "shipped"
          tracking_number: tracking || null,  // required for "shipped"
        },
      });
      router.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  const options = NEXT[order.status];
  if (options.length === 0) return null;

  return (
    <div>
      {order.status === "processing" && (
        <>
          <input value={courier} onChange={(e) => setCourier(e.target.value)} placeholder="Courier (e.g. Delhivery)" />
          <input value={tracking} onChange={(e) => setTracking(e.target.value)} placeholder="Tracking number" />
        </>
      )}
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" />
      {options.map((s) => (
        <button key={s} onClick={() => move(s)}>
          {order.status === "return_requested" && s === "delivered" ? "Reject return" : `Mark ${s.replaceAll("_", " ")}`}
        </button>
      ))}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
```

What happens automatically when you change a status:

| Change | Backend does |
|---|---|
| → `cancelled` | Stock goes back, coupon use is returned, a paid Razorpay order is **fully refunded** |
| → `delivered` on a COD order | Marked as **paid** |
| → `returned` | Stock goes back; Razorpay orders are refunded automatically. **COD returns must be refunded by you** (UPI or bank transfer); the timeline notes this |

Show `order.status_history` as a timeline and `order.payments` as the payment log (with `failure_reason` for failed attempts).

### Products

Product writes use the `/products` routes with an admin token.

| Action | Request |
|---|---|
| List (active only) | `GET /products?page=1&page_size=50&search=...&category_slug=...` |
| Full detail incl. inactive variants | `GET /products/id/{product_id}` |
| Create | `POST /products` |
| Edit | `PATCH /products/{product_id}` (only changed fields) |
| Archive | `DELETE /products/{product_id}` (sets `is_active: false`; old orders keep their data) |
| Add variant | `POST /products/{product_id}/variants` |
| Edit variant / stock | `PATCH /products/variants/{variant_id}` |
| Archive variant | `DELETE /products/variants/{variant_id}` |
| Add image | `POST /products/{product_id}/images` |
| Remove image | `DELETE /products/images/{image_id}` |

> `GET /products` only returns **active** products, so archived ones disappear from the list.
> Keep a link to `/products/id/{id}` (for example in the success message) if you may want to restore one with
> `PATCH /products/{id}` `{ "is_active": true }`.

Create a product with its variants and images in one request:

```ts
const product = await clientApi<ProductDetail>("/products", {
  method: "POST",
  body: {
    category_id: "…",
    name: "Lavender Calm Soap",
    slug: "lavender-calm-soap",          // optional; made from the name if left out
    short_description: "Handmade lavender soap for dry skin",
    description: "…",
    ingredients: "…",
    benefits: "…",
    how_to_use: "…",
    fragrance: "Lavender",
    skin_types: ["dry", "sensitive"],    // lower-cased, spaces become dashes
    is_vegan: true,
    is_handmade: true,
    shelf_life_months: 24,
    hsn_code: "3401",                    // default
    gst_rate: "18",                      // default; 0 to 28
    is_featured: false,
    variants: [
      { sku: "LAV-100", name: "100 g", weight_grams: 100, price: "249", mrp: "299", stock: 50 },
      { sku: "LAV-3PK", name: "Pack of 3", weight_grams: 300, pack_quantity: 3, price: "649", mrp: "897", stock: 20 },
    ],
    images: [
      { image_url: "https://cdn.example.com/lavender-1.jpg", alt_text: "Lavender soap bar", is_primary: true },
    ],
  },
});
```

Rules the backend enforces: SKUs are unique, `mrp` can't be lower than `price`, only one image is primary,
slugs are lowercase words joined with dashes.

Quick stock update from a table:

```ts
await clientApi(`/products/variants/${variantId}`, { method: "PATCH", body: { stock: 120 } });
```

Send prices as strings (`"249.00"`) or numbers; they come back as strings.

> **Images are URLs.** There is no upload endpoint yet. Upload the file to your storage (S3, Cloudinary, ...)
> from the panel and send the resulting URL. A backend upload endpoint is on the to-do list in `BACKEND_GUIDE.md`.

### Categories

| Action | Request |
|---|---|
| List | `GET /products/categories` |
| Create | `POST /products/categories` `{ name, slug?, parent_id?, description?, image_url?, sort_order?, is_active? }` |
| Edit | `PATCH /products/categories/{id}` |
| Archive | `DELETE /products/categories/{id}` |

### Customers

```ts
// Search: matches name, email or phone
const users = await clientApi<Page<AdminUser>>("/admin/users", {
  query: { search: "priya", role: "customer", is_active: true, page: 1, page_size: 50 },
});

await clientApi<AdminUser>(`/admin/users/${id}`);                                                    // detail
await clientApi<AdminUser>(`/admin/users/${id}`, { method: "PATCH", body: { is_active: false } });   // block
await clientApi<AdminUser>(`/admin/users/${id}`, { method: "PATCH", body: { is_active: true } });    // unblock
await clientApi<AdminUser>(`/admin/users/${id}`, { method: "PATCH", body: { role: "admin" } });      // promote
```

Blocking logs the customer out of every device immediately. You can't block or demote **yourself**
(the backend refuses), so hide those buttons on your own row.

### Coupons

```ts
await clientApi<Page<Coupon>>("/admin/coupons", { query: { search: "DIWALI", is_active: true } });

await clientApi<Coupon>("/admin/coupons", {
  method: "POST",
  body: {
    code: "DIWALI20",               // A–Z, 0–9, _ and -, 3 to 50 characters; saved in capitals
    description: "20% off up to ₹200",
    discount_type: "percentage",    // or "flat"
    discount_value: "20",           // percent (max 100) or rupees
    max_discount_amount: "200",     // optional cap for percentage coupons
    min_order_amount: "499",
    usage_limit: 500,               // null = unlimited
    per_user_limit: 1,              // default 1; null = unlimited
    valid_from: "2026-11-01T00:00:00+05:30",
    valid_until: "2026-11-15T23:59:59+05:30",
  },
});

await clientApi<Coupon>(`/admin/coupons/${id}`, { method: "PATCH", body: { is_active: false } }); // pause
await clientApi(`/admin/coupons/${id}`, { method: "DELETE" });                                    // archive
```

Send dates with a timezone (`+05:30`), otherwise they may be read as UTC.
`used_count` goes back down when an order that used the coupon is cancelled.

### Review moderation

```ts
const reviews = await clientApi<Page<Review>>("/admin/reviews", {
  query: { is_approved: true, rating: 1, product_id: undefined, page: 1 },
});
await clientApi<Review>(`/admin/reviews/${id}`, { method: "PATCH", body: { is_approved: false } }); // hide
await clientApi<Review>(`/admin/reviews/${id}`, { method: "PATCH", body: { is_approved: true } });  // restore
```

Hidden reviews disappear from the shop and stop counting toward the product's rating.

---

## 5. Errors you'll see in the panel

Same envelope and handling as the website (section 6 of the website guide). Admin-specific ones:

| HTTP | Code | When |
|---|---|---|
| 400 | `INVALID_STATUS_TRANSITION` | Skipping a step, e.g. `confirmed` → `delivered`. The message lists the allowed statuses |
| 400 | `BAD_REQUEST` | Shipping without courier/tracking, blocking yourself, ... |
| 403 | `FORBIDDEN` | The account isn't an admin any more |
| 409 | `CONFLICT` | Duplicate SKU, slug or coupon code |
| 422 | `VALIDATION_ERROR` | A field is invalid; `errors[].field` says which |
| 502 | `PAYMENT_GATEWAY_ERROR` | A refund couldn't reach Razorpay; try again |

---

## 6. Endpoint cheat sheet

| Method | Path | Body / query |
|---|---|---|
| POST | `/api/auth/login` *(Next.js)* | `{ email, password }` |
| POST | `/api/auth/logout` *(Next.js)* | |
| GET | `/admin/dashboard` | |
| GET | `/admin/orders` | `page, page_size, status, payment_status, payment_method, search, date_from, date_to` |
| GET | `/admin/orders/{id}` | |
| PATCH | `/admin/orders/{id}/status` | `{ status, note?, courier_name?, tracking_number? }` |
| GET | `/admin/users` | `page, page_size, search, role, is_active` |
| GET / PATCH | `/admin/users/{id}` | `{ is_active?, role? }` |
| GET / POST | `/admin/coupons` | `page, page_size, search, is_active` / coupon fields |
| GET / PATCH / DELETE | `/admin/coupons/{id}` | |
| GET | `/admin/reviews` | `page, page_size, product_id, is_approved, rating` |
| PATCH | `/admin/reviews/{id}` | `{ is_approved }` |
| GET | `/products` | `page, page_size, category_slug, skin_type, search, featured` |
| GET | `/products/id/{id}` | |
| POST | `/products` | product + `variants[]` + `images[]` |
| PATCH / DELETE | `/products/{id}` | |
| POST | `/products/{id}/variants` | variant fields |
| PATCH / DELETE | `/products/variants/{id}` | |
| POST | `/products/{id}/images` | `{ image_url, alt_text?, sort_order?, is_primary?, variant_id? }` |
| DELETE | `/products/images/{id}` | |
| GET / POST | `/products/categories` | |
| PATCH / DELETE | `/products/categories/{id}` | |

Page size is capped at 50 on every list. Client components call these through `/api/backend` (`clientApi` adds it).

---

## 7. Before launch

- Host the panel on its own subdomain (e.g. `admin.pebblefeet.in`) and keep it out of search engines
  (`robots: { index: false }` in the root layout's metadata).
- Use a strong password for every admin account; there is no two-factor login yet.
- Serve over HTTPS so the `secure` cookies work.
- Test the full order flow once with Razorpay test keys: place an order on the website, then confirm,
  pack, ship and deliver it from the panel, and try a cancel and a return to check the refunds.
