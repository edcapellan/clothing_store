from flask import render_template
from data import load_products

# -----------------------------
# CATEGORY PAGE METADATA
# -----------------------------
# Each of the four category pages shares one template (category.html).
# This dict drives the page title, tagline copy, and the fallback
# placeholder-block color used when a product doesn't set its own.
CATEGORY_META = {
    "nails": {
        "display": "Nails",
        "tagline": "Little canvases for self-expression.",
        "default_color": "#e7b8c4",
    },
    "accessories": {
        "display": "Accessories",
        "tagline": "The finishing details, considered.",
        "default_color": "#d9c3a3",
    },
    "clothing": {
        "display": "Clothing",
        "tagline": "Draped in softness, dressed in intention.",
        "default_color": "#a9c4d8",
    },
    "jewelry": {
        "display": "Jewelry",
        "tagline": "Small pieces, quietly luxurious.",
        "default_color": "#d4b98c",
    },
}


def _render_category(key):
    meta = CATEGORY_META[key]
    products = load_products()
    items = [p for p in products if p.get("category", "").lower() == key]

    # Which products show in the large "Featured" carousel is controlled
    # explicitly by each product's "featured" flag in products.json,
    # not by their position in the file.
    featured = [p for p in items if p.get("featured")]
    rest = [p for p in items if not p.get("featured")]

    return render_template(
        "category.html",
        active_page=key,
        category_display=meta["display"],
        tagline=meta["tagline"],
        default_color=meta["default_color"],
        featured=featured,
        rest=rest,
    )


def register_routes(app):
    """Registers the four category page routes onto the given Flask app.

    Kept in a separate file from app.py, but uses the same plain
    @app.route style as the rest of the app (no blueprints) so it's
    a drop-in extension rather than a new architectural pattern.
    """

    @app.route("/nails")
    def nails():
        return _render_category("nails")

    @app.route("/accessories")
    def accessories():
        return _render_category("accessories")

    @app.route("/clothing")
    def clothing():
        return _render_category("clothing")

    @app.route("/jewelry")
    def jewelry():
        return _render_category("jewelry")
