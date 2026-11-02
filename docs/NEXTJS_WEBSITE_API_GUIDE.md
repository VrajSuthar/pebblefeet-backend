# Connecting the Next.js Website to the Pebble Feet API

This guide shows how the customer website (Next.js App Router + TypeScript) talks to this
backend: login, products, cart, wishlist, addresses, checkout with Razorpay, orders and reviews.

For the admin panel, see [NEXTJS_ADMIN_API_GUIDE.md](NEXTJS_ADMIN_API_GUIDE.md).
For every backend rule (statuses, coupons, GST), see [../BACKEND_GUIDE.md](../BACKEND_GUIDE.md).

---

## 1. What you need to know about the API first

| Thing | Detail |
|---|---|
| Base URL | `http://localhost:8000` locally (no `/api` or `/v1` prefix) |
| Docs | `http://localhost:8000/docs` shows every request and response shape |
| Auth | `Authorization: Bearer <access_token>` header |
| Access token | Lasts **15 minutes** (`expires_in` is in seconds) |
| Refresh token | Lasts **7 days**. Each refresh returns a **new** refresh token and the old one stops working |
| Money | Decimal fields (`price`, `total`, `subtotal`, ...) arrive as **strings**, e.g. `"249.00"`. Use `Number()` only for display |
| Login required | **Every** endpoint except sign-up, login, refresh, forgot/reset password and `/health`. Products and reviews need a login too |

Every response has the same shape:

```json
{ "status": "success", "status_code": 200, "message": "Login successful", "data": { }, "errors": null }
```

Errors:

```json
{
  "status": "error", "status_code": 422, "message": "Enter a valid 6-digit PIN code",
  "errors": [{ "code": "VALIDATION_ERROR", "message": "Enter a valid 6-digit PIN code", "field": "postal_code" }]
}
```

Use `errors[0].code` to decide what to show; it never changes. `field` tells you which form field to highlight.

> **Products need login right now.** Most shops let people browse first and log in at checkout.
> To allow that, remove `dependencies=[Depends(get_current_user)]` from the product and review
> routers in the backend. Until then, the website must ask people to log in before showing products.

---

## 2. How it fits together

```
 Browser  ──▶  Next.js server  ──▶  FastAPI backend
               (route handlers,
                server components)
```

- The browser **never** sees the tokens. They are stored in **httpOnly cookies** that JavaScript can't read,
  so an XSS bug can't steal them.
- Server components call the backend directly with the token from the cookie.
- Client components call `/api/backend/...` on your own Next.js app, which forwards the request with the token.
  Because the browser only talks to your own domain, **you don't need CORS** on the backend.
- `proxy.ts` (called `middleware.ts` before Next.js 16) refreshes the access token before it expires,
  and sends logged-out visitors to `/login`.

### Files you'll create

```
.env.local
proxy.ts                               # token refresh + login redirect
lib/
├── errors.ts                          # ApiError (safe to import anywhere)
├── types.ts                           # response types
├── backend.ts                         # raw fetch to FastAPI (no Next.js imports)
├── session.ts                         # cookie names + set/clear helpers
├── api.ts                             # for server components / server actions
├── client-api.ts                      # for client components
└── auth-helpers.ts                    # shared by the auth route handlers
app/api/
├── auth/login/route.ts
├── auth/signup/route.ts
├── auth/logout/route.ts
└── backend/[...path]/route.ts         # forwards client requests to FastAPI
```

---

## 3. Environment

`.env.local`:

```bash
# Server-only: no NEXT_PUBLIC_ prefix, so it never reaches the browser
API_URL=http://localhost:8000
```

The Razorpay key isn't needed here: the backend sends it with each order.

---

## 4. Core code

### `lib/errors.ts`

```ts
export type ErrorDetail = { code: string; message: string; field: string | null };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public errors: ErrorDetail[] = [],
  ) {
    super(message);
  }

  /** Error message for one form field, if the backend flagged it. */
  fieldError(field: string) {
    return this.errors.find((e) => e.field === field)?.message;
  }
}
```

### `lib/types.ts`

Only the shapes the website uses. `Money` is a string because Python `Decimal` is sent as a string.

```ts
export type Money = string;

export type ApiResponse<T> = {
  status: "success" | "error";
  status_code: number;
  message: string;
  data: T | null;
  errors: { code: string; message: string; field: string | null }[] | null;
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type Tokens = { access_token: string; refresh_token: string; token_type: string; expires_in: number };
export type AuthUser = { id: string; first_name: string; last_name: string; email: string; phone_number: string };
export type AuthResponse = Tokens & { user: AuthUser };

export type Profile = AuthUser & { role: "admin" | "customer"; is_email_verified: boolean; created_at: string };

export type Address = {
  id: string;
  recipient_name: string;
  phone_number: string;
  address_line1: string;
  address_line2: string | null;
  landmark: string | null;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  address_type: "home" | "work" | "other";
  is_default: boolean;
};

export type Category = {
  id: string; parent_id: string | null; name: string; slug: string;
  description: string | null; image_url: string | null; sort_order: number; is_active: boolean;
};

export type ProductListItem = {
  id: string; name: string; slug: string; short_description: string | null; category_id: string;
  is_featured: boolean; min_price: Money | null; mrp: Money | null; in_stock: boolean;
  primary_image_url: string | null; rating_average: Money | null; review_count: number;
};

export type Variant = {
  id: string; sku: string; name: string; weight_grams: number; pack_quantity: number;
  price: Money; mrp: Money | null; stock: number; is_active: boolean;
};

export type ProductImage = {
  id: string; variant_id: string | null; image_url: string; alt_text: string | null;
  sort_order: number; is_primary: boolean;
};

export type ProductDetail = {
  id: string; name: string; slug: string; short_description: string | null; description: string | null;
  ingredients: string | null; benefits: string | null; how_to_use: string | null; fragrance: string | null;
  skin_types: string[]; is_vegan: boolean; is_handmade: boolean; shelf_life_months: number | null;
  hsn_code: string; gst_rate: Money; is_featured: boolean; is_active: boolean;
  category: Category; variants: Variant[]; images: ProductImage[];
  rating_average: Money | null; review_count: number;
};

export type CartItem = {
  id: string; variant_id: string; product_id: string; product_name: string; product_slug: string;
  variant_name: string; sku: string; image_url: string | null; unit_price: Money; mrp: Money | null;
  quantity: number; line_total: Money; available_stock: number; is_available: boolean; issue: string | null;
};

export type Cart = {
  items: CartItem[]; item_count: number; subtotal: Money; shipping_fee: Money; total: Money;
  amount_for_free_shipping: Money; has_issues: boolean;
};

export type CheckoutPreview = {
  items: { variant_id: string; product_name: string; variant_name: string; image_url: string | null;
           quantity: number; unit_price: Money; line_total: Money }[];
  coupon_code: string | null; subtotal: Money; discount_amount: Money; shipping_fee: Money;
  tax_amount: Money; total_amount: Money; cod_available: boolean;
};

export type OrderStatus =
  | "pending" | "confirmed" | "processing" | "shipped" | "out_for_delivery"
  | "delivered" | "cancelled" | "return_requested" | "returned";
export type PaymentStatus = "pending" | "paid" | "failed" | "refunded" | "partially_refunded";
export type PaymentMethod = "razorpay" | "cod";

export type RazorpayCheckout = {
  key_id: string; razorpay_order_id: string; amount: number; currency: string;
  order_id: string; order_number: string; name: string; description: string;
  prefill: { name: string; email: string; contact: string };
};

export type Order = {
  id: string; order_number: string; status: OrderStatus; payment_status: PaymentStatus;
  payment_method: PaymentMethod; subtotal: Money; discount_amount: Money; shipping_fee: Money;
  tax_amount: Money; total_amount: Money; currency: string; coupon_code: string | null;
  shipping_address: Record<string, string | null>; courier_name: string | null; tracking_number: string | null;
  shipped_at: string | null; delivered_at: string | null; cancelled_at: string | null;
  cancellation_reason: string | null; customer_note: string | null; created_at: string;
  items: { id: string; variant_id: string | null; product_name: string; variant_name: string; sku: string;
           image_url: string | null; quantity: number; unit_price: Money; total_price: Money;
           hsn_code: string; gst_rate: Money }[];
  status_history: { status: OrderStatus; note: string | null; created_at: string }[];
  payments: { id: string; amount: Money; status: "created" | "captured" | "failed" | "refunded";
              method: string | null; razorpay_order_id: string; razorpay_payment_id: string | null;
              failure_reason: string | null; created_at: string }[];
  can_cancel: boolean; can_return: boolean; can_pay: boolean;
};

export type OrderListItem = {
  id: string; order_number: string; status: OrderStatus; payment_status: PaymentStatus;
  payment_method: PaymentMethod; total_amount: Money; item_count: number;
  preview_name: string | null; preview_image_url: string | null; created_at: string;
};

export type PlaceOrderResponse = { order: Order; payment: RazorpayCheckout | null; payment_error: string | null };

export type Review = {
  id: string; product_id: string; reviewer_name: string; rating: number; title: string | null;
  comment: string | null; is_verified_purchase: boolean; is_approved: boolean; created_at: string; updated_at: string;
};

export type ProductReviews = Page<Review> & {
  summary: { average: Money | null; count: number; distribution: Record<string, number> };
};

export type WishlistItem = { product: ProductListItem; added_at: string };
```

### `lib/backend.ts`

The one place that calls FastAPI. It has no Next.js imports, so `proxy.ts` can use it too.

```ts
import { ApiError } from "./errors";
import type { ApiResponse } from "./types";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type Query = Record<string, string | number | boolean | null | undefined>;

export type FetchOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  token?: string;
};

export function buildUrl(path: string, query?: Query) {
  const url = new URL(path, API_URL);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  return url;
}

export async function backendFetch<T>(path: string, { method = "GET", body, query, token }: FetchOptions = {}) {
  const res = await fetch(buildUrl(path, query), {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });

  const json = (await res.json().catch(() => null)) as ApiResponse<T> | null;
  if (!res.ok || !json || json.status === "error") {
    const first = json?.errors?.[0];
    throw new ApiError(res.status, first?.code ?? "UNKNOWN", json?.message ?? res.statusText, json?.errors ?? []);
  }
  return json.data as T;
}
```

### `lib/session.ts`

```ts
import type { Tokens } from "./types";

export const ACCESS_COOKIE = "pf_access";
export const REFRESH_COOKIE = "pf_refresh";
export const EXPIRES_AT_COOKIE = "pf_access_expires_at";
export const DEVICE_COOKIE = "pf_device";

const REFRESH_MAX_AGE = 60 * 60 * 24 * 7; // matches REFRESH_TOKEN_EXPIRE_DAYS

const base = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

// Anything with a cookies-style set/delete: NextResponse.cookies or await cookies()
type CookieStore = {
  set: (name: string, value: string, options: typeof base & { maxAge: number }) => unknown;
  delete: (name: string) => unknown;
};

export function setSession(store: CookieStore, tokens: Tokens) {
  store.set(ACCESS_COOKIE, tokens.access_token, { ...base, maxAge: tokens.expires_in });
  store.set(REFRESH_COOKIE, tokens.refresh_token, { ...base, maxAge: REFRESH_MAX_AGE });
  store.set(EXPIRES_AT_COOKIE, String(Date.now() + tokens.expires_in * 1000), { ...base, maxAge: REFRESH_MAX_AGE });
}

export function clearSession(store: CookieStore) {
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
  store.delete(EXPIRES_AT_COOKIE);
}
```

### `lib/api.ts` (server components and server actions)

```ts
import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { backendFetch, type FetchOptions } from "./backend";
import { ApiError } from "./errors";
import { ACCESS_COOKIE } from "./session";

export async function api<T>(path: string, options: Omit<FetchOptions, "token"> = {}) {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  try {
    return await backendFetch<T>(path, { ...options, token });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) redirect("/login");
    throw error;
  }
}
```

Run `npm install server-only` once. It makes the build fail if this file is ever imported into a client component.

### `lib/client-api.ts` (client components)

```ts
"use client";
import { ApiError } from "./errors";
import type { ApiResponse } from "./types";
import type { Query } from "./backend";

type Options = { method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: unknown; query?: Query };

export async function clientApi<T>(path: string, { method = "GET", body, query }: Options = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.size ? `?${params}` : "";

  const res = await fetch(`/api/backend${path}${qs}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const json = (await res.json().catch(() => null)) as ApiResponse<T> | null;
  if (!res.ok || !json || json.status === "error") {
    if (res.status === 401) {
      window.location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    }
    const first = json?.errors?.[0];
    throw new ApiError(res.status, first?.code ?? "UNKNOWN", json?.message ?? "Something went wrong", json?.errors ?? []);
  }
  return json.data as T;
}
```

### `app/api/backend/[...path]/route.ts` (forwarder)

```ts
import { NextResponse, type NextRequest } from "next/server";
import { buildUrl } from "@/lib/backend";
import { ACCESS_COOKIE } from "@/lib/session";

// These hand out or revoke tokens, so they go through /api/auth/* instead
const BLOCKED = new Set(["auth/login", "auth/sign-up", "auth/refresh", "auth/logout", "payments/webhook/razorpay"]);

async function forward(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const path = (await params).path.join("/");
  if (BLOCKED.has(path)) return NextResponse.json({ message: "Not found" }, { status: 404 });

  const url = buildUrl(`/${path}`);
  url.search = req.nextUrl.search;
  const token = req.cookies.get(ACCESS_COOKIE)?.value;

  const res = await fetch(url, {
    method: req.method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.text(),
    cache: "no-store",
  });

  return new NextResponse(res.body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

export { forward as GET, forward as POST, forward as PATCH, forward as DELETE };
```

### `lib/auth-helpers.ts`

The backend asks for a `device_name` and `player_id` (used for push notifications in the app).
On the web we send the browser name and a random ID kept in a cookie.

```ts
import { NextResponse, type NextRequest } from "next/server";
import { ApiError } from "./errors";
import { DEVICE_COOKIE } from "./session";

export function deviceInfo(req: NextRequest) {
  const playerId = req.cookies.get(DEVICE_COOKIE)?.value ?? `web-${crypto.randomUUID()}`;
  const deviceName = `Web: ${req.headers.get("user-agent") ?? "browser"}`.slice(0, 100);
  return { device_name: deviceName, player_id: playerId };
}

export function rememberDevice(res: NextResponse, playerId: string) {
  res.cookies.set(DEVICE_COOKIE, playerId, { httpOnly: true, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 365 });
}

export function errorJson(error: unknown) {
  if (error instanceof ApiError) {
    return NextResponse.json(
      { status: "error", status_code: error.status, message: error.message, errors: error.errors },
      { status: error.status },
    );
  }
  return NextResponse.json({ status: "error", message: "Server unavailable" }, { status: 502 });
}
```

### `app/api/auth/login/route.ts`

```ts
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { deviceInfo, errorJson, rememberDevice } from "@/lib/auth-helpers";
import { setSession } from "@/lib/session";
import type { AuthResponse } from "@/lib/types";

export async function POST(req: NextRequest) {
  const { email, password } = await req.json();
  const device = deviceInfo(req);
  try {
    const data = await backendFetch<AuthResponse>("/auth/login", {
      method: "POST",
      body: { email, password, ...device },
    });
    const res = NextResponse.json({ status: "success", data: { user: data.user } });
    setSession(res.cookies, data);
    rememberDevice(res, device.player_id);
    return res;
  } catch (error) {
    return errorJson(error);
  }
}
```

### `app/api/auth/signup/route.ts`

```ts
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { deviceInfo, errorJson, rememberDevice } from "@/lib/auth-helpers";
import { setSession } from "@/lib/session";
import type { AuthResponse } from "@/lib/types";

export async function POST(req: NextRequest) {
  // { first_name, last_name, phone_number, email, password, confirm_password }
  const form = await req.json();
  const device = deviceInfo(req);
  try {
    const data = await backendFetch<AuthResponse>("/auth/sign-up", { method: "POST", body: { ...form, ...device } });
    const res = NextResponse.json({ status: "success", data: { user: data.user } });
    setSession(res.cookies, data);
    rememberDevice(res, device.player_id);
    return res;
  } catch (error) {
    return errorJson(error);
  }
}
```

Sign-up rules: password 8 to 64 characters with an uppercase letter, a lowercase letter and a digit;
`confirm_password` must match; phone is 10 to 15 digits with an optional `+`.

### `app/api/auth/logout/route.ts`

```ts
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { ACCESS_COOKIE, REFRESH_COOKIE, clearSession } from "@/lib/session";

export async function POST(req: NextRequest) {
  const token = req.cookies.get(ACCESS_COOKIE)?.value;
  const refreshToken = req.cookies.get(REFRESH_COOKIE)?.value;
  if (token && refreshToken) {
    // Revokes the refresh token on the server; ignore failures, we log out locally anyway
    await backendFetch("/auth/logout", { method: "POST", token, body: { refresh_token: refreshToken } }).catch(() => {});
  }
  const res = NextResponse.json({ status: "success" });
  clearSession(res.cookies);
  return res;
}
```

### `proxy.ts` (token refresh and login redirect)

Put it in the project root (next to `app/`). On Next.js 15 name the file `middleware.ts` and the
function `middleware`.

```ts
import { NextResponse, type NextRequest } from "next/server";
import { backendFetch } from "@/lib/backend";
import { ACCESS_COOKIE, EXPIRES_AT_COOKIE, REFRESH_COOKIE, clearSession, setSession } from "@/lib/session";
import type { Tokens } from "@/lib/types";

// Pages anyone can open. Add "/" and "/products" once product browsing is public in the backend.
const PUBLIC_PAGES = ["/login", "/signup", "/forgot-password"];

// A refresh token works only once. If two requests refresh with the same token at the same moment,
// the backend treats the second as a stolen token and logs the user out everywhere.
// Sharing one refresh per token prevents that within this server process.
const inflight = new Map<string, Promise<Tokens | null>>();

function refreshOnce(refreshToken: string) {
  let pending = inflight.get(refreshToken);
  if (!pending) {
    pending = backendFetch<Tokens>("/auth/refresh", { method: "POST", body: { refresh_token: refreshToken } })
      .catch(() => null)
      .finally(() => setTimeout(() => inflight.delete(refreshToken), 10_000));
    inflight.set(refreshToken, pending);
  }
  return pending;
}

export async function proxy(req: NextRequest) {
  const refreshToken = req.cookies.get(REFRESH_COOKIE)?.value;
  const expiresAt = Number(req.cookies.get(EXPIRES_AT_COOKIE)?.value ?? 0);

  // undefined: no refresh needed · null: refresh failed · Tokens: refreshed
  let refreshed: Tokens | null | undefined;
  if (refreshToken && Date.now() > expiresAt - 60_000) {
    refreshed = await refreshOnce(refreshToken);
    // Update this request's cookies so server components see the new token straight away
    if (refreshed) req.cookies.set(ACCESS_COOKIE, refreshed.access_token);
    else req.cookies.delete(ACCESS_COOKIE);
  }

  const { pathname, search } = req.nextUrl;
  const isPublic = pathname.startsWith("/api/") || PUBLIC_PAGES.some((p) => pathname.startsWith(p));
  const loggedIn = req.cookies.has(ACCESS_COOKIE);

  const res =
    !loggedIn && !isPublic
      ? NextResponse.redirect(new URL(`/login?next=${encodeURIComponent(pathname + search)}`, req.url))
      : NextResponse.next({ request: { headers: req.headers } });

  if (refreshed) setSession(res.cookies, refreshed);
  else if (refreshed === null) clearSession(res.cookies);
  return res;
}

export const config = {
  // Everything except static files and images
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|svg|webp|ico)$).*)"],
};
```

`/api/*` routes are not redirected (they return 401 JSON instead), but they still pass through
`proxy.ts`, so they get the token refresh too.

---

## 5. Pages

### Login page (client component)

```tsx
"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const next = useSearchParams().get("next") ?? "/";
  const [error, setError] = useState("");

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
    });
    if (!res.ok) {
      setError((await res.json()).message ?? "Login failed");
      return;
    }
    router.replace(next);
    router.refresh();
  }

  return (
    <form onSubmit={onSubmit}>
      <input name="email" type="email" required />
      <input name="password" type="password" required />
      {error && <p role="alert">{error}</p>}
      <button>Log in</button>
    </form>
  );
}
```

Wrap the page in `<Suspense>` (or read `searchParams` from the page props) because it uses `useSearchParams`.

### Product list (server component)

```tsx
// app/products/page.tsx
import Link from "next/link";
import { api } from "@/lib/api";
import type { Category, Page, ProductListItem } from "@/lib/types";

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; category?: string; q?: string; skin?: string }>;
}) {
  const sp = await searchParams;
  const [products, categories] = await Promise.all([
    api<Page<ProductListItem>>("/products", {
      query: { page: sp.page ?? 1, page_size: 20, category_slug: sp.category, search: sp.q, skin_type: sp.skin },
    }),
    api<Category[]>("/products/categories"),
  ]);

  return (
    <main>
      <nav>
        {categories.map((c) => (
          <Link key={c.id} href={`/products?category=${c.slug}`}>{c.name}</Link>
        ))}
      </nav>
      {products.items.map((p) => (
        <Link key={p.id} href={`/products/${p.slug}`}>
          {p.primary_image_url && <img src={p.primary_image_url} alt={p.name} />}
          <h2>{p.name}</h2>
          <p>
            ₹{p.min_price}
            {p.mrp && p.mrp !== p.min_price && <s> ₹{p.mrp}</s>}
          </p>
          {!p.in_stock && <span>Out of stock</span>}
          {p.rating_average && <span>★ {p.rating_average} ({p.review_count})</span>}
        </Link>
      ))}
      <p>Page {products.page} of {Math.ceil(products.total / products.page_size)}</p>
    </main>
  );
}
```

Query options for `GET /products`: `page`, `page_size` (max 50), `category_slug`, `skin_type`, `search`, `featured=true`.

### Product detail with reviews

```tsx
// app/products/[slug]/page.tsx
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { ProductDetail, ProductReviews } from "@/lib/types";
import { AddToCart } from "./add-to-cart";

export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const product = await api<ProductDetail>(`/products/${slug}`).catch((e) => {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  });
  const reviews = await api<ProductReviews>(`/reviews/product/${product.id}`, { query: { page: 1 } });

  return (
    <main>
      <h1>{product.name}</h1>
      {product.images.map((img) => <img key={img.id} src={img.image_url} alt={img.alt_text ?? product.name} />)}
      <AddToCart variants={product.variants} />
      <p>{product.description}</p>

      <h2>Reviews: ★ {reviews.summary.average ?? "–"} ({reviews.summary.count})</h2>
      {[5, 4, 3, 2, 1].map((star) => (
        <div key={star}>{star}★ {reviews.summary.distribution[star] ?? 0}</div>
      ))}
      {reviews.items.map((r) => (
        <article key={r.id}>
          <strong>{r.reviewer_name}</strong> {"★".repeat(r.rating)}
          {r.is_verified_purchase && <span> Verified purchase</span>}
          {r.title && <h3>{r.title}</h3>}
          <p>{r.comment}</p>
        </article>
      ))}
    </main>
  );
}
```

### Add to cart (client component)

```tsx
// app/products/[slug]/add-to-cart.tsx
"use client";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";
import { ApiError } from "@/lib/errors";
import type { Cart, Variant } from "@/lib/types";

export function AddToCart({ variants }: { variants: Variant[] }) {
  const [variantId, setVariantId] = useState(variants[0]?.id);
  const [message, setMessage] = useState("");

  async function add() {
    try {
      const cart = await clientApi<Cart>("/cart/items", { method: "POST", body: { variant_id: variantId, quantity: 1 } });
      setMessage(`Added. ${cart.item_count} items in cart`);
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Could not add to cart");
    }
  }

  return (
    <div>
      {variants.map((v) => (
        <label key={v.id}>
          <input type="radio" checked={variantId === v.id} onChange={() => setVariantId(v.id)} disabled={v.stock === 0} />
          {v.name} · ₹{v.price} {v.stock === 0 && "(out of stock)"}
        </label>
      ))}
      <button onClick={add} disabled={!variantId}>Add to cart</button>
      <p>{message}</p>
    </div>
  );
}
```

Adding the same variant again **increases** the quantity. One item is capped at 10 and the cart at 30 different items.

### Cart page

```tsx
"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { clientApi } from "@/lib/client-api";
import type { Cart } from "@/lib/types";

export default function CartPage() {
  const [cart, setCart] = useState<Cart | null>(null);

  useEffect(() => { clientApi<Cart>("/cart").then(setCart); }, []);

  const setQty = async (itemId: string, quantity: number) =>
    setCart(await clientApi<Cart>(`/cart/items/${itemId}`, { method: "PATCH", body: { quantity } }));
  const remove = async (itemId: string) =>
    setCart(await clientApi<Cart>(`/cart/items/${itemId}`, { method: "DELETE" }));

  if (!cart) return <p>Loading…</p>;
  if (cart.items.length === 0) return <p>Your cart is empty</p>;

  return (
    <main>
      {cart.items.map((item) => (
        <div key={item.id}>
          {item.product_name} ({item.variant_name}) · ₹{item.unit_price}
          <input type="number" min={1} max={10} value={item.quantity}
                 onChange={(e) => setQty(item.id, Number(e.target.value))} />
          ₹{item.line_total}
          <button onClick={() => remove(item.id)}>Remove</button>
          {!item.is_available && <p role="alert">{item.issue}</p>}
        </div>
      ))}
      <p>Subtotal ₹{cart.subtotal} · Shipping ₹{cart.shipping_fee} · Total ₹{cart.total}</p>
      {Number(cart.amount_for_free_shipping) > 0 && (
        <p>Add ₹{cart.amount_for_free_shipping} more for free shipping</p>
      )}
      {cart.has_issues
        ? <p>Fix the items above to continue</p>
        : <Link href="/checkout">Checkout</Link>}
    </main>
  );
}
```

`has_issues` is true when an item went out of stock or was removed. The backend refuses checkout until it's fixed.

### Addresses

| Action | Request |
|---|---|
| List | `GET /users/me/addresses` |
| Add | `POST /users/me/addresses` |
| Edit | `PATCH /users/me/addresses/{id}` (send only changed fields) |
| Delete | `DELETE /users/me/addresses/{id}` |

```ts
await clientApi<Address>("/users/me/addresses", {
  method: "POST",
  body: {
    recipient_name: "Priya Shah",
    phone_number: "9876543210",
    address_line1: "12, Lake View Society",
    address_line2: "Near City Mall",     // optional
    landmark: null,                       // optional
    city: "Ahmedabad",
    state: "Gujarat",
    postal_code: "380015",                // 6 digits, can't start with 0
    address_type: "home",                 // home | work | other
    is_default: true,
  },
});
```

There is always exactly one default address; making one default un-defaults the others.

### Checkout with Razorpay

Flow: preview totals → place order → open Razorpay → verify.

```tsx
// app/checkout/page.tsx
"use client";
import Script from "next/script";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clientApi } from "@/lib/client-api";
import { ApiError } from "@/lib/errors";
import type { Address, CheckoutPreview, Order, PlaceOrderResponse, RazorpayCheckout } from "@/lib/types";

declare global {
  interface Window { Razorpay: new (options: object) => { open(): void; on(event: string, cb: (r: any) => void): void } }
}

export default function CheckoutPage() {
  const router = useRouter();
  const [addresses, setAddresses] = useState<Address[]>([]);
  const [addressId, setAddressId] = useState<string>();
  const [coupon, setCoupon] = useState("");
  const [preview, setPreview] = useState<CheckoutPreview | null>(null);
  const [method, setMethod] = useState<"razorpay" | "cod">("razorpay");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    clientApi<Address[]>("/users/me/addresses").then((list) => {
      setAddresses(list);
      setAddressId(list.find((a) => a.is_default)?.id ?? list[0]?.id);
    });
    clientApi<CheckoutPreview>("/orders/preview", { method: "POST", body: {} }).then(setPreview);
  }, []);

  async function applyCoupon() {
    try {
      setPreview(await clientApi<CheckoutPreview>("/orders/preview", { method: "POST", body: { coupon_code: coupon } }));
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Invalid coupon"); // e.g. COUPON_EXPIRED, COUPON_MIN_ORDER
    }
  }

  function openRazorpay(payment: RazorpayCheckout) {
    const rzp = new window.Razorpay({
      key: payment.key_id,
      order_id: payment.razorpay_order_id,
      amount: payment.amount, // paise
      currency: payment.currency,
      name: payment.name,
      description: payment.description,
      prefill: payment.prefill,
      handler: async (r: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) => {
        try {
          const order = await clientApi<Order>("/payments/verify", { method: "POST", body: r });
          router.replace(`/orders/${order.id}?placed=1`);
        } catch (e) {
          // PAYMENT_PENDING: Razorpay hasn't confirmed yet. The webhook will finish it, so show the order anyway
          router.replace(`/orders/${payment.order_id}`);
        }
      },
      modal: {
        // Customer closed the popup: the order stays unpaid, they can retry from the order page
        ondismiss: () => router.replace(`/orders/${payment.order_id}`),
      },
    });
    rzp.on("payment.failed", () => setError("Payment failed. You can retry from your order page."));
    rzp.open();
  }

  async function placeOrder() {
    if (!addressId) return;
    setBusy(true);
    setError("");
    try {
      const res = await clientApi<PlaceOrderResponse>("/orders", {
        method: "POST",
        body: { address_id: addressId, payment_method: method, coupon_code: preview?.coupon_code ?? null },
      });
      if (res.payment) openRazorpay(res.payment);
      else router.replace(`/orders/${res.order.id}?placed=1`); // COD, or Razorpay was unreachable (payment_error)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not place the order"); // CART_EMPTY, CART_ITEM_UNAVAILABLE, ...
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <Script src="https://checkout.razorpay.com/v1/checkout.js" strategy="afterInteractive" />

      {addresses.map((a) => (
        <label key={a.id}>
          <input type="radio" checked={addressId === a.id} onChange={() => setAddressId(a.id)} />
          {a.recipient_name}, {a.address_line1}, {a.city} {a.postal_code}
        </label>
      ))}

      <input value={coupon} onChange={(e) => setCoupon(e.target.value)} placeholder="Coupon code" />
      <button onClick={applyCoupon}>Apply</button>

      {preview && (
        <dl>
          <dt>Subtotal</dt><dd>₹{preview.subtotal}</dd>
          <dt>Discount</dt><dd>−₹{preview.discount_amount}</dd>
          <dt>Shipping</dt><dd>₹{preview.shipping_fee}</dd>
          <dt>Total</dt><dd>₹{preview.total_amount}</dd>
          <dd><small>Includes ₹{preview.tax_amount} GST</small></dd>
        </dl>
      )}

      <label><input type="radio" checked={method === "razorpay"} onChange={() => setMethod("razorpay")} /> Pay online</label>
      {preview?.cod_available && (
        <label><input type="radio" checked={method === "cod"} onChange={() => setMethod("cod")} /> Cash on delivery</label>
      )}

      {error && <p role="alert">{error}</p>}
      <button onClick={placeOrder} disabled={busy || !addressId}>Place order</button>
    </main>
  );
}
```

Important points:
- Placing an order **reserves stock and empties the cart** straight away, even before payment.
- An unpaid Razorpay order is cancelled automatically after **30 minutes** and the stock goes back.
- Always send the verify call. If the customer closes the tab before it, the Razorpay webhook still confirms the order.
- Prices already include GST. Show `tax_amount` as "includes", never add it on top.

### Orders

```tsx
// app/orders/page.tsx
import Link from "next/link";
import { api } from "@/lib/api";
import type { OrderListItem, Page } from "@/lib/types";

export default async function OrdersPage({ searchParams }: { searchParams: Promise<{ page?: string }> }) {
  const { page = "1" } = await searchParams;
  const orders = await api<Page<OrderListItem>>("/orders", { query: { page, page_size: 10 } });
  return (
    <main>
      {orders.items.map((o) => (
        <Link key={o.id} href={`/orders/${o.id}`}>
          {o.order_number} · {o.status} · ₹{o.total_amount} · {o.item_count} items
        </Link>
      ))}
    </main>
  );
}
```

On the order detail page (`GET /orders/{id}`), show buttons from the flags the backend sends:

| Flag | Button | Request |
|---|---|---|
| `can_pay` | Pay now | `POST /orders/{id}/pay` → returns a `RazorpayCheckout`; open it exactly like checkout |
| `can_cancel` | Cancel order | `POST /orders/{id}/cancel` with `{ "reason": "Ordered by mistake" }` (reason optional) |
| `can_return` | Return | `POST /orders/{id}/return` with `{ "reason": "Damaged on arrival" }` (3 to 500 characters) |

Show `status_history` as the tracking timeline, and `courier_name` + `tracking_number` once shipped.
Cancelling a paid order refunds it automatically.

Customer-facing status labels:

| Status | Show as |
|---|---|
| `pending` | Awaiting payment |
| `confirmed` | Order confirmed |
| `processing` | Being packed |
| `shipped` | Shipped |
| `out_for_delivery` | Out for delivery |
| `delivered` | Delivered |
| `cancelled` | Cancelled |
| `return_requested` | Return requested |
| `returned` | Returned |

### Reviews

```ts
// Write (one review per product)
await clientApi<Review>("/reviews", { method: "POST", body: { product_id, rating: 5, title: "Lovely", comment: "Smells great" } });
// Edit my review
await clientApi<Review>(`/reviews/${reviewId}`, { method: "PATCH", body: { rating: 4 } });
// Delete my review
await clientApi(`/reviews/${reviewId}`, { method: "DELETE" });
```

### Wishlist

```ts
await clientApi<WishlistItem[]>("/wishlist");                                           // list
await clientApi<WishlistItem[]>("/wishlist", { method: "POST", body: { product_id } });  // add
await clientApi(`/wishlist/${productId}`, { method: "DELETE" });                         // remove
```

### Profile and account

```ts
await clientApi<Profile>("/users/me");
await clientApi<Profile>("/users/me", { method: "PATCH", body: { first_name: "Priya", phone_number: "9876543210" } });
await clientApi("/auth/change-password", { method: "POST", body: { old_password, new_password } });
await clientApi("/users/me/delete", { method: "POST", body: { password } }); // then POST /api/auth/logout
```

### Forgot password (3 steps, no login needed)

```ts
await clientApi("/auth/forgot-password", { method: "POST", body: { email } });              // 1. sends a 6-digit OTP
await clientApi("/auth/forgot-password/verify", { method: "POST", body: { email, otp } });  // 2. check the OTP
await clientApi("/auth/reset-password", {                                                   // 3. set the new password
  method: "POST",
  body: { email, otp, new_password, confirm_password },
});
```

> OTP emails are only **logged** by the backend for now (no email provider is connected yet).
> During development, read the OTP from the backend's console.

---

## 6. Handling errors

```ts
try {
  await clientApi("/orders", { method: "POST", body });
} catch (e) {
  if (!(e instanceof ApiError)) throw e;
  switch (e.code) {
    case "VALIDATION_ERROR":
      // show e.fieldError("postal_code") next to that field
      break;
    case "CART_EMPTY":
      router.push("/cart");
      break;
    default:
      toast(e.message); // backend messages are written for customers
  }
}
```

| HTTP | Meaning | What to do |
|---|---|---|
| 400 | Request refused by a business rule (coupon, stock, cancel window) | Show the message |
| 401 | Not logged in, token expired or invalid, account disabled | Send to `/login` (`client-api.ts` does this) |
| 403 | Not allowed | Show the message |
| 404 | Not found (also returned for another customer's order or address) | Not-found page |
| 409 | Conflict (e.g. already reviewed, phone already used) | Show the message |
| 422 | Validation error | Highlight `errors[].field` |
| 502 | Razorpay unreachable (`PAYMENT_GATEWAY_ERROR`) | "Payment service is busy, try again" |
| 5xx / network | Backend down | "Something went wrong, try again" |

Codes the website will see:

| Code | When |
|---|---|
| `VALIDATION_ERROR` | A field is invalid; check `field` |
| `INVALID_CREDENTIALS` | Wrong email or password |
| `TOKEN_EXPIRED`, `TOKEN_INVALID`, `UNAUTHORIZED` | Log in again |
| `ACCOUNT_DISABLED` | The account was blocked by an admin |
| `OTP_INVALID`, `OTP_EXPIRED` | Forgot-password OTP is wrong or too old |
| `CART_EMPTY` | Placing an order with an empty cart |
| `CART_ITEM_UNAVAILABLE` | An item is out of stock or no longer sold |
| `COUPON_INVALID`, `COUPON_EXPIRED`, `COUPON_EXHAUSTED`, `COUPON_ALREADY_USED`, `COUPON_MIN_ORDER` | Coupon problems |
| `PAYMENT_SIGNATURE_INVALID` | The verify call got a tampered response |
| `PAYMENT_PENDING` | Razorpay hasn't confirmed the payment yet; the webhook will |
| `NOT_FOUND`, `CONFLICT`, `BAD_REQUEST`, `FORBIDDEN` | General cases; show `message` |

---

## 7. Endpoint cheat sheet

| Method | Path | Body / query |
|---|---|---|
| POST | `/api/auth/login` *(Next.js)* | `{ email, password }` |
| POST | `/api/auth/signup` *(Next.js)* | `{ first_name, last_name, phone_number, email, password, confirm_password }` |
| POST | `/api/auth/logout` *(Next.js)* | |
| GET | `/products` | `page, page_size, category_slug, skin_type, search, featured` |
| GET | `/products/categories` | |
| GET | `/products/{slug}` | |
| GET | `/reviews/product/{product_id}` | `page, page_size, rating` |
| POST / PATCH / DELETE | `/reviews`, `/reviews/{id}` | `{ product_id, rating, title?, comment? }` |
| GET / POST | `/wishlist` | `{ product_id }` |
| DELETE | `/wishlist/{product_id}` | |
| GET / DELETE | `/cart` | |
| POST | `/cart/items` | `{ variant_id, quantity }` |
| PATCH / DELETE | `/cart/items/{id}` | `{ quantity }` |
| GET / PATCH | `/users/me` | `{ first_name?, last_name?, phone_number? }` |
| POST | `/users/me/delete` | `{ password }` |
| GET / POST | `/users/me/addresses` | address fields |
| GET / PATCH / DELETE | `/users/me/addresses/{id}` | |
| POST | `/orders/preview` | `{ coupon_code? }` |
| POST | `/orders` | `{ address_id, payment_method, coupon_code?, customer_note? }` |
| GET | `/orders` | `page, page_size, status` |
| GET | `/orders/{id}` | |
| POST | `/orders/{id}/pay` | |
| POST | `/orders/{id}/cancel` | `{ reason? }` |
| POST | `/orders/{id}/return` | `{ reason }` |
| POST | `/payments/verify` | `{ razorpay_order_id, razorpay_payment_id, razorpay_signature }` |
| POST | `/auth/forgot-password`, `/auth/forgot-password/verify`, `/auth/reset-password` | see above |
| POST | `/auth/change-password` | `{ old_password, new_password }` |

Client components call these through `/api/backend` (e.g. `/api/backend/cart`); `clientApi` adds that prefix for you.

---

## 8. Before launch

- Set `API_URL` to the production backend URL in your hosting settings.
- Serve the site over HTTPS so the `secure` cookies work.
- Test a full payment with Razorpay **test** keys and the UPI ID `success@razorpay`, then switch the backend to live keys.
- **Refresh token races on serverless hosting.** The single shared refresh in `proxy.ts` only works within one
  server process. On Vercel or other serverless hosts, two requests can land on different instances and refresh
  at the same time, which logs the user out. If you see unexpected logouts, add a short grace period to the
  backend's refresh endpoint (accept a just-rotated token for a few seconds).
- Ask for public product browsing in the backend if you want visitors to see products before logging in.
