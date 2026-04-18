from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import stripe
import json
import os

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

# Stripe Keys
stripe.api_key = "sk_test_123456"
PUBLISHABLE_KEY = "pk_test_123456"

# Product storage
PRODUCTS_FILE = "products.json"
ADMIN_PASSWORD = "admin123"


# -----------------------------
# PRODUCT HELPERS
# -----------------------------
def load_products():
    if not os.path.exists(PRODUCTS_FILE):
        return []
    with open(PRODUCTS_FILE, "r") as f:
        return json.load(f)


def save_products(products):
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(products, f, indent=4)


# -----------------------------
# HOME PAGE
# -----------------------------
@app.route("/")
def home():
    products = load_products()
    categories = {}

    for item in products:
        categories.setdefault(item["category"], []).append(item)

    return render_template("home.html", categories=categories)


# -----------------------------
# CART SYSTEM
# -----------------------------
@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    product = request.form.get("product")
    price = request.form.get("price")

    if not product or not price:
        return redirect(url_for("home"))

    try:
        price = float(price)
    except ValueError:
        price = 0.00

    cart = session.get("cart", [])
    cart.append({"product": product, "price": round(price, 2)})
    session["cart"] = cart

    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    cart = session.get("cart", [])
    total = sum(item["price"] for item in cart)
    return render_template("cart.html", cart=cart, total=round(total, 2))


@app.route("/remove_from_cart/<int:index>")
def remove_from_cart(index):
    cart = session.get("cart", [])
    if 0 <= index < len(cart):
        cart.pop(index)
    session["cart"] = cart
    return redirect(url_for("cart"))


# -----------------------------
# CHECKOUT + STRIPE
# -----------------------------
@app.route("/checkout")
def checkout():
    cart = session.get("cart", [])
    total = sum(item["price"] for item in cart)

    return render_template(
        "checkout.html",
        cart=cart,
        total=round(total, 2),
        STRIPE_PUBLISHABLE_KEY=PUBLISHABLE_KEY,
        total_amount_in_cents=int(total * 100)
    )


@app.route("/create-payment-intent", methods=["POST"])
def create_payment_intent():
    data = request.get_json()
    amount = data.get("amount")

    if not amount:
        return jsonify({"error": "Missing amount"}), 400

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(amount),
            currency="usd",
            automatic_payment_methods={"enabled": True},
        )
        return jsonify({"clientSecret": intent.client_secret})

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/success")
def success():
    session["cart"] = []
    return render_template("success.html")


@app.route("/error")
def error():
    return render_template("error.html", error="Payment failed")


# -----------------------------
# ADMIN PANEL
# -----------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", error="Wrong password")

    return render_template("admin_login.html")


@app.route("/admin")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    products = load_products()
    return render_template("admin_dashboard.html", products=products)


@app.route("/admin/add", methods=["GET", "POST"])
def admin_add():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        products = load_products()

        new_product = {
            "id": products[-1]["id"] + 1 if products else 1,
            "name": request.form["name"],
            "price": float(request.form["price"]),
            "image": request.form["image"],
            "category": request.form["category"],
            "description": request.form["description"],
            "in_stock": request.form.get("in_stock") == "on",
            "slug": request.form["name"].lower().replace(" ", "-")
        }

        products.append(new_product)
        save_products(products)

        return redirect(url_for("admin_dashboard"))

    return render_template("admin_add.html")


@app.route("/admin/edit/<int:product_id>", methods=["GET", "POST"])
def admin_edit(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    products = load_products()
    product = next((p for p in products if p["id"] == product_id), None)

    if not product:
        return "Product not found"

    if request.method == "POST":
        product["name"] = request.form["name"]
        product["price"] = float(request.form["price"])
        product["image"] = request.form["image"]
        product["category"] = request.form["category"]
        product["description"] = request.form["description"]
        product["in_stock"] = request.form.get("in_stock") == "on"
        product["slug"] = request.form["name"].lower().replace(" ", "-")

        save_products(products)
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_edit.html", product=product)


@app.route("/admin/delete/<int:product_id>")
def admin_delete(product_id):
    if not session.get("admin"):
        return redirect(url_for("admin_login"))

    products = load_products()
    products = [p for p in products if p["id"] != product_id]
    save_products(products)

    return redirect(url_for("admin_dashboard"))


# -----------------------------
# RUN APP
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)