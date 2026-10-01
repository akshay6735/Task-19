# ShopEasy — E-Commerce Platform

Full-stack app: **React (Vite) + Flask + MySQL**.

## 1. Database

Open a MySQL shell (or MySQL Workbench) and run:

```sql
source backend/schema.sql;
```

This creates the `ecommerce` database and all tables (fresh install).

**If you already have the database set up** from before these new features
(ratings/wishlist/coupons/dashboard) were added, don't re-run `schema.sql`
(it would wipe your data) — instead run the migration, which only adds
what's new:

```powershell
Get-Content backend/migrate_v2.sql | mysql -u root -p ecommerce
```

## 2. Backend (Flask)

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Open `config.py` and set your MySQL `user` / `password`.

Seed sample data (4 categories, 20 products, an admin + a customer account):

```bash
python seed.py
```

Start the API:

```bash
python app.py
```

Runs at **http://localhost:5000**.

Demo logins created by `seed.py`:
| Role     | Email                | Password    |
|----------|-----------------------|-------------|
| Admin    | admin@example.com     | admin123    |
| Customer | customer@example.com  | customer123 |

## 3. Frontend (React + Vite)

In a new terminal:

```bash
cd frontend
npm install
npm run dev
```

Runs at **http://localhost:5173** and talks to the API at `localhost:5000`
(cookies are sent cross-origin via `withCredentials: true` + Flask-CORS).

## 4. Try it out

1. Visit `http://localhost:5173`, browse products, filter/search/sort.
2. Register a new account (or log in as the demo customer), add items to
   the cart, check out with an address. Try coupon code `WELCOME10` or
   `SAVE20` (seeded automatically) at checkout.
3. After an order is delivered (or really, right away — the check is just
   "have you purchased this product"), go to the product page and leave a
   star rating + review.
4. Click the heart icon on any product to add it to your wishlist, and
   view it all at `/wishlist`.
5. Log in as the demo admin to add/edit/delete products, manage orders,
   manage coupons at `/admin/coupons`, and view the sales dashboard at
   `/admin`.

## New features (v10 - real-time notifications via WebSockets)

Needs a database migration AND two new Python packages:

```powershell
Get-Content backend/migrate_v5.sql | mysql -u root -p ecommerce
pip install flask-socketio eventlet
cd frontend
npm install socket.io-client
```

**Note:** `eventlet` prints a deprecation warning on import these days (its
maintainers are steering people toward other async libraries). It still
works fine and is what the task specifically asks for - the warning is
expected and harmless for this project.

**Also note:** the backend now starts with `socketio.run(...)` instead of
`app.run(...)`, with `use_reloader=False`. Flask's auto-reload-on-save
doesn't play well with eventlet's process model, so you'll need to
manually restart `python app.py` after editing backend code from now on.

- When a customer places an order, every admin gets a live notification -
  no refresh needed - via a persistent WebSocket connection
  (Flask-SocketIO + socket.io-client).
- New `notifications` table, new `SocketContext` (`src/context/SocketContext.jsx`)
  and a bell icon with a dropdown (`src/components/NotificationBell.jsx`) in
  the Navbar, for any logged-in user.
- Four new REST routes so notifications persist across refreshes:
  `GET /api/notifications`, `PUT /api/notifications/<id>/read`,
  `PUT /api/notifications/read-all`, `DELETE /api/notifications/<id>`.
- **Security fix vs. the original task spec:** the spec's design has the
  client tell the server its own role in a `join` message after connecting
  (`socket.emit('join', { user_id, role })`) - which means any logged-in
  customer could simply claim `role: 'admin'` and silently receive every
  order notification (including other customers' order totals). Instead,
  the socket connection is authenticated with the same JWT access token
  already used for REST calls (sent as `{ auth: { token } }` when opening
  the connection); the server decodes it and joins rooms based on what the
  token actually says, never what the client claims. There's no `join`
  event at all - it's redundant once the server does this at connect time.
  This is covered by an automated test that proves a customer spoofing
  `role: 'admin'` gets nothing.
- **Fix vs. the spec's sample code:** the spec's own `markAsRead` only
  updated local React state and never called the backend - so a page
  refresh would silently un-read everything. It's now a real `PUT` to
  `/api/notifications/<id>/read`. Likewise, order notifications are
  inserted one row per admin (not a single bulk `INSERT...SELECT`) so each
  admin's live notification carries their own real database id from the
  moment it arrives - meaning they can mark it read or dismiss it
  immediately, with no need to wait for a refresh to "reconcile" a
  placeholder id.
- `unreadCount` is derived from the notification list (`useMemo`) rather
  than tracked as a separate incrementing counter, so it can never drift
  out of sync after a delete or a bulk mark-all-read.
- All four REST routes scope every query to the logged-in user's own id,
  so one user can never read, mark-read, or delete another user's
  notification by guessing an id.
- Dropping a notification (the × button) only deletes it - it does not
  also mark it read first, so dismissing something you haven't looked at
  doesn't pretend you read it.

## New features (v9 - profile page upgrades)

No database migration needed - these reuse the orders/users tables as they are.

- **"Member since" now shows month + year** ("Member since Jan 2025"), not
  the full date.
- **Account Activity section** - new `GET /api/me/stats` returns the user's
  total order count and total amount spent (cancelled orders excluded from
  the spend total). Shown as two stat cards, reusing the same card styles
  as the admin dashboard.
- **Delete Account** - a "Danger Zone" section with a confirm modal
  (`components/ConfirmModal.jsx`, reusable, closes on Cancel/Escape/backdrop
  click). Confirming calls the new `DELETE /api/me`, then clears the JWTs
  and redirects home.
  - Backend design choice: this is a **hard delete**. It removes the
    user's orders (and their order_items, which cascade automatically),
    then the user row itself (which cascades to ratings and wishlist, since
    those already had `ON DELETE CASCADE`). Their avatar file is deleted
    from disk too. If you'd rather keep order history for accounting/legal
    reasons, replace this with an "anonymize" step instead of a real delete.
- **Password strength meter** under the New Password field - a 5-point
  score (length, length bonus, mixed case, digit, symbol) shown as a
  coloured bar + label (Weak/Fair/Good/Strong/Very Strong). It's a UI hint
  only; the backend's actual rule is still just the 6-character minimum.

## New features (v8 - user profile & settings)

Needs a one-line database migration - run it BEFORE starting the new backend:

```powershell
Get-Content backend/migrate_v4.sql | mysql -u root -p ecommerce
```

- **`/profile` page** (logged-in users only) with three sections: profile
  picture, edit name/email, change password. Linked from the Navbar
  ("My Profile", and by clicking your avatar/name).
- **Profile picture** - pick a file, see an instant preview, click Upload.
  The Navbar avatar changes immediately. No photo yet? A circle with the
  user's initials is shown. Uploading a new photo deletes the old file.
- **Backend** - `GET /api/me` now returns the full profile (email,
  avatar_url, created_at) from the database; new `PUT /api/me` (name/email,
  409 if the email is taken), `PUT /api/me/password` (verifies the current
  password first) and `PUT /api/me/avatar` (upload + save in one step).
- **`updateUser()` in AuthContext** - merges changed fields into the shared
  user, so the Navbar reflects edits instantly without a refresh.
- **New helpers** - `useForm` (values/validation/errors/submit),
  `useToast` (success/error notifications) and an `Avatar` component. The
  form, toast and avatar styles all use the theme variables, so the page
  works in light, dark and sepia.
- **Bug fix in `api.js`** - the interceptor used to treat *every* 401 as an
  expired token. It now refreshes only when the server says
  `token_expired`. Without this, a wrong password on the login page reloaded
  the page and hid the error, and a wrong *current* password on the profile
  page would have triggered a needless token refresh. `app.py` and `api.js`
  must be updated together for this to work.
- Emails are now saved lowercase when edited (as they already are at
  register), because login looks emails up in lowercase.

## New features (v7 - theme system upgrades)

- **Smooth transitions** - a global rule now animates
  `background-color`/`color`/`border-color` over 0.3s on every element
  when the theme switches, instead of colors snapping instantly. Elements
  with their own transition (like buttons) keep their existing feel for
  hover/press - only the color-related properties are affected.
- **Third theme: Sepia** - a warm, low-glare reading theme
  (`:root[data-theme='sepia']` in `index.css`), with its own tinted badge/
  status colors tuned for a cream background.
- **Live OS theme following** - `ThemeContext` now subscribes to
  `window.matchMedia('(prefers-color-scheme: dark)')`'s `change` event,
  so if the visitor flips their OS between light/dark, the app follows in
  real time - but only until they've made an explicit choice of their own
  (clicking the toggle, including picking sepia). Once they've picked a
  theme themselves, it sticks even if their OS theme changes afterward.
- The navbar toggle now **cycles** light → dark → sepia → light, showing
  the icon of the theme you'll switch *to* next.

## New features (v6 - dark mode & theme system)

Pure frontend change - no backend or database changes.

- New `ThemeContext` (`src/context/ThemeContext.jsx`) - tracks `'light'`
  or `'dark'`, checks `localStorage` first, then falls back to the
  browser's `prefers-color-scheme` on first visit. Every change is
  saved back to `localStorage` and applied as `data-theme` on
  `<html>`.
- `main.jsx` now wraps everything in `<ThemeProvider>`.
- A 🌙/☀️ toggle button sits in the Navbar (`useTheme()`).
- `index.css` was restructured around CSS custom properties: brand
  colors (`--primary`, `--accent`, `--gold`, etc.) stay constant across
  themes, while surface/text/border tokens
  (`--bg-primary`, `--text-primary`, `--card-bg`, `--border-color`, and
  several tinted badge/status colors) switch between a light and a dark
  value set under `:root[data-theme='light']` / `:root[data-theme='dark']`.
  A bare `:root` fallback (= light values) prevents a flash of
  unstyled colors before React mounts.
- Every page listed in the task (Navbar, product cards, product detail,
  cart, checkout, orders, admin pages, login/register) now reads its
  colors from these variables instead of hardcoded hex values, so
  toggling the theme updates the whole app instantly with no
  per-component logic.
- A couple of things were deliberately left theme-independent: the
  colorful navbar gradient, dashboard stat-card gradients, and small
  overlay buttons drawn on top of product images - these already have
  good contrast in both themes and don't need to change.

## New features (v5 - JWT authentication)

Auth is now stateless JWT instead of Flask sessions - this is a bigger
change than earlier upgrades, so read this section before testing.

- **`pip install flask-jwt-extended`** is a new backend dependency
  (already added to `requirements.txt`).
- `POST /api/login` and `POST /api/register` now return
  `{ access_token, refresh_token, user }` instead of setting a session
  cookie. Access tokens expire in 15 minutes; refresh tokens in 7 days.
- Every previously-session-protected route now uses `@login_required` /
  `@admin_required`, which are thin wrappers around flask-jwt-extended's
  `@jwt_required()` - same decorator names as before, so route code
  barely changed, but they now check a `Bearer` token in the
  `Authorization` header instead of a cookie.
- New `POST /api/refresh` route - exchanges a valid refresh token for a
  new access token.
- `GET /api/me` now requires a valid access token and returns the user
  object directly (`{ id, name, role }`), not wrapped in `{ user: ... }`.
- **Frontend**: `api.js` now attaches `Authorization: Bearer <token>` to
  every request via an Axios request interceptor, and a response
  interceptor automatically retries any request that comes back 401 by
  silently refreshing the access token first. If the refresh token has
  also expired, the user is logged out and sent to `/login`.
- Tokens live in `localStorage` (`access_token` / `refresh_token`).
  `AuthContext` restores the logged-in user on page refresh by calling
  `/api/me` if a token is present, so reloading the page no longer logs
  you out.
- No database changes. No new tables.

**One consequence to know about:** because access tokens now expire
after 15 minutes, staying logged in for longer than that no longer
"just works" via a cookie - it depends on the refresh flow actually
firing on the next API call after expiry. This is expected and correct
JWT behavior, not a bug: the interceptor handles it silently as long as
the refresh token (7-day lifetime) is still valid.

## New features (v4 - pagination + debounced search)

- **`GET /api/products`** now takes `?page=&limit=&search=&category=&sort=`
  and returns `{ products, total, page, limit, total_pages }` instead of a
  bare array. Uses `LIMIT`/`OFFSET` server-side, so only one page of rows
  is ever fetched.
- **`GET /api/orders`** (admin) takes `?page=&limit=` the same way, returning
  `{ orders, total, page, limit, total_pages }`.
- **`useDebounce` hook** (`src/hooks/useDebounce.js`) — the search input
  updates on every keystroke (no typing lag), but the value used to
  trigger an API call only updates 300ms after the user stops typing.
- **`Pagination` component** (`src/components/Pagination.jsx`) — Previous/
  Next buttons, numbered pages, current page highlighted. Used on the
  Home page (products, 8/page) and `/admin/orders` (10/page).
- Changing the search text, category, or sort on Home resets back to
  page 1 automatically.
- `AdminProducts.jsx` (the admin management table) isn't paginated per
  this task's spec, so it just requests a high `limit` to keep showing
  everything at once - it was updated only to unwrap the new response
  shape.

## New features (v3 - image upload upgrades)

- **Drag-and-drop upload** — the admin product form's image inputs are now
  a `DropzoneUpload` component: drag a file onto it, or click to browse.
- **Old file cleanup** — when a product's cover image is replaced, or the
  product is deleted, the old file(s) are removed from
  `backend/static/uploads/` on disk, not just unlinked in the database.
- **Product image gallery** — a `product_images` table holds extra photos
  per product. Manage them from the product's edit page (upload/delete
  each one); the product detail page shows a thumbnail strip that swaps
  the large image. Needs `migrate_v3.sql` if you're updating an existing
  database.
- **Upload progress** — both the cover image and gallery uploads show a
  live percentage bar via Axios's `onUploadProgress`.

## New features (v2)

- **Product ratings** — customers who've purchased a product can leave a
  1–5 star rating + optional review (`ratings` table). One rating per
  user per product; submitting again updates it.
- **Wishlist** — heart icon on any product card/detail page, backed by a
  `wishlist` table and a `WishlistContext` (same pattern as the cart).
- **Coupons** — `coupons` table with a code, discount %, active flag, and
  optional expiry. Validated live at checkout (`POST /api/coupons/validate`)
  and re-validated server-side when the order is placed, so a coupon can't
  be forged or reused after being deactivated. Admins manage coupons at
  `/admin/coupons`.
- **Low stock warnings** — any product with stock < 5 shows an amber
  "Only N left" badge on product cards, the detail page, and the admin
  product table. The dashboard also shows a running low-stock count.
- **Admin sales dashboard** (`/admin`) — total revenue (excluding
  cancelled orders), total order count, low-stock count, and a top-5
  best-selling products table by units sold.

## How the pieces fit together

- **CartContext** (`src/context/CartContext.jsx`) holds the cart in
  React state (persisted to `localStorage` so a refresh doesn't lose it).
  Any component calls `useCart()` to read/update it — no prop drilling.
- **AuthContext** (`src/context/AuthContext.jsx`) holds the logged-in
  user, backed by the Flask session cookie. `ProtectedRoute` and
  `AdminRoute` read `useAuth()` to guard pages.
- **Stock safety**: `POST /api/orders` first checks every item has
  enough stock, and only *after* every item passes does it create the
  order and decrement stock — so a failed order never partially reduces
  inventory.
- **Price history**: `order_items.unit_price` is copied from the
  product at order time, so later price changes never rewrite past
  orders.

## Notes / things you may want to extend

- Passwords are hashed with bcrypt; sessions are Flask's signed cookie
  sessions (fine for this project — swap for JWT if you need a
  stateless API later).
- `config.py` has DB credentials in plain text for simplicity — use
  environment variables before deploying anywhere real.
- Product images use placeholder URLs (picsum.photos) from `seed.py` —
  swap in real image URLs any time via the admin edit form.
