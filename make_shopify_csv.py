"""Turn products.xlsx (your master list) into a CSV that Shopify can import.

    python make_shopify_csv.py                                  # no photos in the file
    python make_shopify_csv.py --site-url https://noemicloset.onrender.com

With --site-url, each local photo becomes a public link (SITE/static/images/set1.jpg)
that Shopify downloads during import. The site must already be live for that to work.
Then in Shopify: Products > Import > upload shopify_products.csv.

Only the standard Shopify import columns are written (extra/misnamed columns make
imports fail). If Shopify ever changes its template, compare the header row below with
the sample CSV from Products > Import.
"""
import argparse
import csv
import html
from urllib.parse import quote

import data

COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Type", "Tags", "Published",
    "Option1 Name", "Option1 Value", "Variant SKU", "Variant Grams",
    "Variant Inventory Tracker", "Variant Inventory Qty", "Variant Inventory Policy",
    "Variant Fulfillment Service", "Variant Price", "Variant Requires Shipping",
    "Variant Taxable", "Image Src", "Image Position", "Image Alt Text", "Gift Card", "Status",
]
VENDOR = "Noemi Closet"


def image_url(product, site_url):
    img = product.get("image")
    if not img or not product.get("image_ok"):
        return ""
    if img.startswith(("http://", "https://")):
        return img
    if not site_url:
        return ""
    return "%s/static/%s" % (site_url.rstrip("/"), quote(img))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url", default="", help="your live site, e.g. https://noemicloset.onrender.com")
    ap.add_argument("--out", default="shopify_products.csv")
    ap.add_argument("--stock", type=int, default=10,
                    help="inventory quantity for every in-stock item (default 10); sold-out items get 0")
    args = ap.parse_args()

    products = data.load_products(force=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for p in products:
            src = image_url(p, args.site_url)
            tags = ", ".join(t for t in (p["category"], p["subcategory"]) if t)
            row = {
                "Handle": p["slug"],
                "Title": p["name"],
                "Body (HTML)": "<p>%s</p>" % html.escape(p["description"]) if p["description"] else "",
                "Vendor": VENDOR,
                "Type": p["category"],
                "Tags": tags,
                "Published": "TRUE",
                "Option1 Name": "Title",
                "Option1 Value": "Default Title",
                "Variant SKU": p["slug"],
                "Variant Grams": "0",             # set real weights in Shopify for shipping rates
                "Variant Inventory Tracker": "shopify",
                "Variant Inventory Qty": str(args.stock),
                "Variant Price": "%.2f" % p["price"],
                "Variant Inventory Policy": "deny",   # Shopify requires deny or continue on every row
                "Variant Fulfillment Service": "manual",
                "Variant Requires Shipping": "TRUE",
                "Variant Taxable": "TRUE",
                "Image Src": src,
                "Image Position": "1" if src else "",
                "Image Alt Text": p["name"] if src else "",
                "Gift Card": "FALSE",
                "Status": "active",
            }
            if not p["in_stock"]:
                row["Variant Inventory Qty"] = "0"   # sold out here -> can't be bought on Shopify either
            w.writerow(row)

    with_photos = sum(1 for p in products if image_url(p, args.site_url))
    print("Wrote %d products to %s (%d with photo links)." % (len(products), args.out, with_photos))
    if not args.site_url and any(p["image_ok"] for p in products):
        print("Note: no --site-url given, so photo links were left blank (upload photos in Shopify "
              "or re-run with your live site address).")


if __name__ == "__main__":
    main()
