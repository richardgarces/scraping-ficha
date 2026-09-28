import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash
try:
    from .opencompare_transform import transform_products
except Exception:
    # allow running as a script from the tools/editor_py folder
    from opencompare_transform import transform_products

try:
    from pymongo import MongoClient
except Exception:
    MongoClient = None

APP_DIR = os.path.dirname(__file__)
DATA_FILE = os.path.join(APP_DIR, "products.json")

app = Flask(__name__)
app.secret_key = os.environ.get("EDITOR_SECRET", "dev-secret")


def get_db():
    uri = os.environ.get("MONGODB_URI")
    if uri and MongoClient:
        client = MongoClient(uri)
        return client.get_default_database()
    return None


def load_products():
    db = get_db()
    if db is not None:
        coll = db.get_collection("products")
        return list(coll.find({}, {"_id": 0}))
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_product(doc):
    db = get_db()
    if db is not None:
        coll = db.get_collection("products")
        # upsert by product_id + store
        query = {"product_id": doc.get("product_id"), "store": doc.get("store")}
        coll.update_one(query, {"$set": doc}, upsert=True)
        return True
    # fallback: write file
    products = load_products()
    updated = False
    for i, p in enumerate(products):
        if p.get("product_id") == doc.get("product_id") and p.get("store") == doc.get("store"):
            products[i] = doc
            updated = True
            break
    if not updated:
        products.append(doc)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    return True


@app.route("/admin")
def admin_index():
    products = load_products()
    return render_template("index.html", products=products)


@app.route("/admin/export_opencompare")
def export_opencompare():
    products = load_products()
    oc = transform_products(products)
    return (json.dumps(oc, ensure_ascii=False, indent=2), 200, {"Content-Type": "application/json; charset=utf-8"})


@app.route("/admin/edit/<store>/<product_id>", methods=["GET", "POST"])
def edit_product(store, product_id):
    products = load_products()
    doc = next((p for p in products if p.get("store") == store and p.get("product_id") == product_id), None)
    if request.method == "POST":
        name = request.form.get("name")
        brand = request.form.get("brand")
        rating = request.form.get("rating")
        reviews = request.form.get("reviews")
        specs = request.form.get("specs")
        try:
            specs_obj = json.loads(specs) if specs else {}
        except Exception:
            flash("Especificaciones JSON inválido", "error")
            return redirect(request.url)
        newdoc = {
            "store": store,
            "product_id": product_id,
            "name": name,
            "brand": brand,
            "rating": float(rating) if rating else None,
            "reviews": int(reviews) if reviews else None,
            "specifications": specs_obj,
        }
        save_product(newdoc)
        flash("Guardado correctamente", "success")
        return redirect(url_for("admin_index"))
    return render_template("edit.html", doc=doc or {"store": store, "product_id": product_id})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5008)), debug=True)
