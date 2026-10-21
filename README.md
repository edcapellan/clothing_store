# Noemi Closet LLC - Flask + Stripe store

## Run locally
```
python -m venv .venv && .venv\Scripts\activate      (Windows)
pip install -r requirements.txt
python app.py        # http://localhost:5000
```
Without env vars it runs in dev mode with insecure defaults (admin password `admin123`, checkout disabled).

## Managing products (the spreadsheet)
All products live in **products.xlsx** (tab "Products"; read the "Instructions" tab).
Columns: Name, Category, Subcategory, Price, Image, Description, In Stock, Featured, Visible, Placeholder Color.
Photos go in `static/images/`; put just the file name in the Image column (e.g. `set4.jpg`).
Edit, save, `git add . && git commit && git push` - Render redeploys.

**Edit live with Google Sheets (optional):** upload products.xlsx to Google Sheets, then
File > Share > Publish to web > pick the Products tab + "Comma-separated values (.csv)" > Publish,
and set the env var `PRODUCTS_SHEET_URL` to that link. The site refreshes every 5 minutes
(`PRODUCTS_CACHE_SECONDS`). If Google is unreachable, the last good copy / products.xlsx is used.

The Admin page (`/admin`) lists every spreadsheet row the site couldn't use and why.

## Environment variables (set on Render)
| Name | Required | Purpose |
|---|---|---|
| FLASK_SECRET | yes | Signs session cookies. Long random string. |
| ADMIN_PASSWORD | yes | Admin login. Use a strong one. |
| STRIPE_SECRET / STRIPE_PUBLIC | for checkout | `sk_...` / `pk_...` keys (test keys while testing) |
| SHOW_BANNER / BANNER_TEXT | no | "Under construction" banner. On by default; `SHOW_BANNER=false` hides it |
| PRODUCTS_SHEET_URL | no | Google Sheet CSV link |
| DATA_DIR | no | Folder on a persistent disk for orders.json |

The app refuses to start on Render if FLASK_SECRET or ADMIN_PASSWORD is missing.

## Orders
Stripe Dashboard is the permanent record of payments (and sends customer receipts).
`orders.json` is a convenience copy shown on /admin; on Render's free tier its disk resets on
each deploy, so set `DATA_DIR` to a persistent disk if you want to keep it.
