import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

import stripe
from urllib.parse import urlparse

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)

from category_routes import register_routes
from data import (get_load_report, get_product, load_orders, load_products,
                  record_order)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -----------------------------
# CONFIG
# -----------------------------
# Render sets RENDER=true automatically. In production the app REFUSES to start
# without real secrets instead of quietly running with guessable defaults.
IS_PRODUCTION = bool(os.getenv("RENDER")) or os.getenv("FLASK_ENV") == "production"


def _required_secret(name, dev_default):
    value = os.getenv(name)
    if value:
        return value
    if IS_PRODUCTION:
        raise RuntimeError(
            "%s is not set. Add it under Environment on your host (Render) before deploying." % name
        )
    app.logger.warning("%s not set - using an insecure development default.", name)
    return dev_default


app.secret_key = _required_secret("FLASK_SECRET", "dev-only-secret-change-me")
ADMIN_PASSWORD = _required_secret("ADMIN_PASSWORD", "admin123")

stripe.api_key = os.getenv("STRIPE_SECRET")
PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLIC")
if not (stripe.api_key and PUBLISHABLE_KEY):
    app.logger.warning("STRIPE_SECRET / STRIPE_PUBLIC not set - checkout is disabled.")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,   # cookies only over HTTPS in production
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

# Countries you ship to. Add e.g. "CA": "Canada" to open up more.
SHIPPING_COUNTRIES = {"US": "United States"}
MAX_CART_ITEMS = 20
BRAND = "Noemi Closet LLC"


# -----------------------------
# TEMPLATE HELPERS
# -----------------------------
@app.template_global()
def product_image_src(product):
    """URL of a product's photo, or None (template then shows the color block)."""
    image = product.get("image")
    if not image or not product.get("image_ok"):
        return None
    if image.startswith(("http://", "https://")):
        return image
    return url_for("static", filename=image)


@app.context_processor
def inject_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return {
        "csrf_token": session["csrf"],
        "brand": BRAND,
        "cart_count": len([x for x in session.get("cart", []) if isinstance(x, str)]),
        "settings": {
            # Banner is ON by default. Set SHOW_BANNER=false on Render to hide it.
            "show_banner": os.getenv("SHOW_BANNER", "true").lower() not in ("0", "false", "no"),
            "banner_text": os.getenv("BANNER_TEXT",
                                     "Our website is under construction. Thanks for your patience!"),
        },
    }


def _same(a, b):
    """Constant-time string compare that never raises on odd characters."""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def _csrf_ok():
    sent = request.form.get("csrf_token", "")
    return bool(sent) and _same(sent, session.get("csrf", ""))


# -----------------------------
# HOME PAGE
# -----------------------------
@app.route("/")
def home():
    return render_template("home.html", active_page="home")


# -----------------------------
# CATEGORY PAGES (Nails, Accessories, Clothing, Jewelry)
# -----------------------------
register_routes(app)


# -----------------------------
# CART SYSTEM
# -----------------------------
# The session stores ONLY product ids (slugs). Names and prices are looked up
# from the spreadsheet every time, so a customer can't change a price by editing
# the form, and a product you later hide / mark sold out drops out of carts.
def build_cart():
    """Return (lines, total_cents, removed_count) priced from the spreadsheet."""
    catalog = {p["slug"]: p for p in load_products()}
    stored = [s for s in session.get("cart", []) if isinstance(s, str)]
    valid = [s for s in stored if s in catalog and catalog[s]["in_stock"]]
    removed = len(stored) - len(valid)
    if removed or stored != session.get("cart", []):
        session["cart"] = valid

    lines = []
    for index, slug in enumerate(valid):
        p = catalog[slug]
        lines.append({
            "index": index,
            "slug": slug,
            "product": p["name"],
            "price": p["price"],
            "price_cents": p["price_cents"],
        })
    return lines, sum(l["price_cents"] for l in lines), removed


def _back():
    """Send the customer back to the page they were on (same site only)."""
    ref = request.referrer
    if ref and urlparse(ref).netloc == request.host:
        return redirect(ref)
    return redirect(url_for("home"))


@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    slug = request.form.get("slug", "").strip()
    product = get_product(slug) if slug else None
    is_fetch = request.headers.get("X-Requested-With") == "fetch"

    if not product or not product["in_stock"]:
        message = "This product is no longer available."
        if is_fetch:
            return jsonify({"error": message}), 404
        flash(message)
        return _back()

    cart = session.get("cart", [])
    if len(cart) >= MAX_CART_ITEMS:
        message = "Your cart has reached its item limit."
        if is_fetch:
            return jsonify({"error": message}), 400
        flash(message)
        return _back()

    cart.append(product["slug"])
    session["cart"] = cart

    message = "%s added to your cart." % product["name"]
    if is_fetch:
        return jsonify({"count": len(cart), "message": message})
    flash(message)
    return _back()


@app.route("/cart")
def cart():
    lines, total_cents, removed = build_cart()
    return render_template("cart.html", cart=lines, total=total_cents / 100, removed=removed)


@app.route("/remove_from_cart/<int:index>")
def remove_from_cart(index):
    stored = session.get("cart", [])
    if 0 <= index < len(stored):
        stored.pop(index)
    session["cart"] = stored
    return redirect(url_for("cart"))


# -----------------------------
# CHECKOUT + STRIPE
# -----------------------------
@app.route("/checkout")
def checkout():
    lines, total_cents, _ = build_cart()
    if not lines:
        return redirect(url_for("cart"))
    return render_template(
        "checkout.html",
        cart=lines,
        total=total_cents / 100,
        STRIPE_PUBLISHABLE_KEY=PUBLISHABLE_KEY,
        payments_ready=bool(stripe.api_key and PUBLISHABLE_KEY),
        countries=SHIPPING_COUNTRIES,
    )


def _clean(value, limit=100):
    return str(value or "").strip()[:limit]


@app.route("/create-payment-intent", methods=["POST"])
def create_payment_intent():
    if not (stripe.api_key and PUBLISHABLE_KEY):
        return jsonify({"error": "Payments are not set up yet."}), 503

    lines, total_cents, _ = build_cart()
    if not lines:
        return jsonify({"error": "Your cart is empty."}), 400
    if total_cents < 50:  # Stripe's minimum charge is $0.50
        return jsonify({"error": "The order total is too small to charge."}), 400

    body = request.get_json(silent=True) or {}
    ship = body.get("shipping") or {}
    name = _clean(body.get("name"))
    email = _clean(body.get("email"), 120)
    address = {
        "line1": _clean(ship.get("line1")),
        "line2": _clean(ship.get("line2")),
        "city": _clean(ship.get("city")),
        "state": _clean(ship.get("state"), 50),
        "postal_code": _clean(ship.get("postal_code"), 10),
        "country": _clean(ship.get("country"), 2).upper(),
    }

    problem = None
    if len(name) < 2:
        problem = "Please enter your name."
    elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        problem = "Please enter a valid email address."
    elif not (address["line1"] and address["city"] and address["state"]):
        problem = "Please enter your full shipping address."
    elif address["country"] not in SHIPPING_COUNTRIES:
        problem = "Sorry, we don't ship to that country yet."
    elif address["country"] == "US" and not re.match(r"^\d{5}(-\d{4})?$", address["postal_code"]):
        problem = "Please enter a valid 5-digit ZIP code."
    if problem:
        return jsonify({"error": problem}), 400

    items_text = "; ".join("%s ($%.2f)" % (l["product"], l["price"]) for l in lines)
    try:
        intent = stripe.PaymentIntent.create(
            amount=total_cents,                      # computed server-side, in whole cents
            currency="usd",
            automatic_payment_methods={"enabled": True},
            receipt_email=email,
            shipping={
                "name": name,
                "address": {k: v for k, v in address.items() if v},
            },
            metadata={
                "customer_name": name,
                "item_count": len(lines),
                "items": items_text[:490],
            },
        )
    except Exception:
        app.logger.exception("Stripe PaymentIntent.create failed")
        return jsonify({"error": "We couldn't start the payment. Please try again."}), 502

    # Snapshot of exactly what this payment is for (slug, cents)
    session["checkout"] = {
        "pi": intent.id,
        "items": [[l["slug"], l["price_cents"]] for l in lines],
    }
    return jsonify({"clientSecret": intent.client_secret, "paymentIntentId": intent.id})


# -----------------------------
# SUCCESS + ORDER SAVING
# -----------------------------
# /success is only trusted after asking Stripe whether this exact payment
# succeeded. Visiting the URL by hand does nothing.
@app.route("/success")
def success():
    pi_id = request.args.get("payment_intent", "")
    checkout_info = session.get("checkout")

    # Customer refreshed the page after we already recorded the order
    if not (checkout_info and _same(pi_id, checkout_info.get("pi", ""))):
        if pi_id and pi_id == session.get("last_pi"):
            for existing in load_orders():
                if existing.get("payment_intent") == pi_id:
                    return render_template("success.html", order=existing)
        return redirect(url_for("home"))

    try:
        intent = stripe.PaymentIntent.retrieve(pi_id)
    except Exception:
        app.logger.exception("Could not verify PaymentIntent %s", pi_id)
        return render_template(
            "error.html",
            error="We couldn't confirm your payment yet. If you were charged, "
                  "you'll get a Stripe receipt by email - please contact us.",
        ), 502

    if intent.get("status") != "succeeded":
        return render_template("error.html", error="Your payment didn't go through. "
                               "You have not been charged."), 402

    catalog = {p["slug"]: p for p in load_products()}
    items = []
    for slug, cents in checkout_info["items"]:
        items.append({
            "product": catalog[slug]["name"] if slug in catalog else slug,
            "slug": slug,
            "price": cents / 100,
        })

    ship = intent.get("shipping") or {}
    addr = ship.get("address") or {}
    meta = intent.get("metadata") or {}
    paid_cents = intent.get("amount", 0)
    if paid_cents != sum(c for _, c in checkout_info["items"]):
        app.logger.error("Amount mismatch on %s: paid %s", pi_id, paid_cents)

    order, _created = record_order({
        "payment_intent": pi_id,
        "name": ship.get("name") or meta.get("customer_name") or "Unknown",
        "email": intent.get("receipt_email") or "Unknown",
        "shipping": {k: addr.get(k, "") for k in
                     ("line1", "line2", "city", "state", "postal_code", "country")},
        "items": items,
        "total": paid_cents / 100,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    session["cart"] = []
    session.pop("checkout", None)
    session["last_pi"] = pi_id
    return render_template("success.html", order=order)


@app.route("/error")
def error():
    return render_template("error.html", error="Payment failed")


# -----------------------------
# ADMIN PANEL
# -----------------------------
# Products are managed in the spreadsheet (products.xlsx or your Google Sheet),
# so the panel is for checking the catalog and viewing orders.
def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if _same(request.form.get("password") or "", ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", error="Wrong password"), 401
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    if _csrf_ok():
        session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin_dashboard.html",
        products=load_products(),
        report=get_load_report(),
        orders=list(reversed(load_orders())),
    )


@app.route("/admin/reload", methods=["POST"])
@admin_required
def admin_reload():
    if _csrf_ok():
        load_products(force=True)
    return redirect(url_for("admin_dashboard"))


# -----------------------------
# RUN APP
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
