# Nyon Derma — storefront redesign

Multi-page redesign of nyonderma.com with a store admin dashboard. Plain HTML/CSS/JS, no build step.

## Run it

```
python serve.py
```

Then open http://localhost:5510. The admin is at http://localhost:5510/admin.html.

## Pages

| Page | What it does |
|---|---|
| `index.html` | Home: hero, shop by concern, everyday essentials, studio facials, best sellers, results and reviews |
| `shop.html` | Full catalogue (36 products) with concern, category and price filters, search, sort |
| `product.html?p=<slug>` | Product detail with gallery, quantity, routine guidance, related products |
| `treatments.html` | Seva Wellness Studio treatment menu; booking goes to booking.nyonderma.com |
| `about.html` | Full story, versatility, values, CEO, team, what we treat, timeline, results, reviews, latest articles |
| `contact.html` | FAQ (shipping, returns) and message form |
| `cart.html` | Checkout: delivery details, zone, payment method |
| `blog.html` | Skin School: the 8 real articles from nyonderma.com/blog, with topic filter |
| `article.html?a=<slug>` | Article reader with a related product and more articles |
| `routine.html` | Step-by-step routines for every skincare set, morning and night |
| `help.html` | Full customer help centre (orders, shipping, returns) with search |
| `rewards.html` | Reward points: earn 10 for shopping, newsletter, profile, referrals |
| `message.html?t=<token>` | Customer's private conversation page (linked from reply emails) |
| `account.html` | Sign in / register, orders, points, affiliate referral link, details |
| `track.html` | Order tracking by order number + phone |
| `favourites.html` | Products saved with the heart button |
| `policies.html` | Shipping, returns, payments (from the live help page) + draft privacy and terms |
| `404.html` | Page-not-found, served by `serve.py` for missing URLs |
| `admin.html` | Dashboard: overview, orders, products (add/edit/hide/delete), bookings, messages, customers |


## Running the store (admin.html)

- **Products**: add, edit, hide or delete; set a sale price and optional end date per product.
- **Sales & discounts**: put a whole category (or everything) on sale by percent, end sales, and create discount codes (percent or ₵ off, minimum spend, expiry, on/off). Codes are applied at checkout.
- **Skin School**: write, edit, schedule (future date), save as draft or delete articles, with a cover photo. Blank lines separate paragraphs, `## ` starts a heading, `- ` a bullet.
- **Settings**: announcement bar text/link, the booking page address, and delivery fees per zone.
- **Bookings**: links out to https://booking.nyonderma.com/, which is where Nyon Derma already takes treatment bookings. Every "Book" button on the site goes there.

## Customer messages (contact form → admin inbox → email reply)

`serve.py` also runs a small API (Python standard library only, no installs):

- The contact form saves messages to `data/messages.db` (SQLite) on the server.
- Admin → **Messages** needs the admin password. Pick a conversation, write a reply and send.
- Replies are emailed through SMTP. Each email has a private link to `message.html`, where the customer can read the thread and reply; their reply goes back to **Needs reply**.
- If a customer left only a phone number, the reply is saved and the admin gets a WhatsApp button with the conversation link, plus a call button.
- Until SMTP is set up, replies are written to `outbox/` as readable `.txt` files instead of being sent.

### Setup

1. Copy `.env.example` to `.env` and set `ADMIN_PASSWORD` (if it's empty, a one-off password is printed when the server starts).
2. For real email, fill in `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_SECURITY`, `MAIL_FROM` and `REPLY_TO`. Gmail needs an app password; any provider with SMTP works (Zoho, Brevo, Mailgun, Google Workspace).
3. Set `SITE_URL` to the public address so links in emails work (default `http://localhost:5510`).

`.env`, `data/` and `outbox/` are git-ignored and are never served by the site, along with `backend/`, `tests/` and `*.py`.

### Tests

```
python -m unittest discover -s tests -v
```

## How data works

- `assets/js/data.js` holds the catalogue taken from the live store (names, prices in ₵, categories, descriptions, photos).
- Cart, orders, bookings, messages and product edits are saved in the browser's `localStorage`, so the shop and admin stay in sync on one machine. This is a prototype: for production, replace `Store` in `assets/js/app.js` with calls to WooCommerce (or another backend) and put the admin behind a login.
- The admin seeds sample orders, bookings and messages on first load (marked as samples). Use "Remove sample data" in the admin to clear them.

## To confirm with Nyon Derma

- Delivery fees (admin → Settings) are placeholders: Accra ₵30, rest of Ghana ₵50.
- Privacy policy and terms of sale on `policies.html` are drafts for Nyon Derma to review.
- Payment options (Mobile Money, card, pay on delivery) don't process payments yet.
- The About timeline years for 2021–2024 are estimates.
- Accounts and reward points are saved in this browser only (no passwords are stored); replace with WooCommerce accounts.
- Board of Advisors and "In the press" from the old About page are left out: the live site lists no names or outlets.
- Product → skin concern tags in `data.js` were assigned from product descriptions.
