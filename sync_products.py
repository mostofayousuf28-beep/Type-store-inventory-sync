import os
import time
import random
import requests

DROPSHIP_API_KEY = os.environ.get("DROPSHIP_API_KEY")
DROPSHIP_SECRET_KEY = os.environ.get("DROPSHIP_SECRET_KEY")
SHOPIFY_STORE_DOMAIN = os.environ.get("SHOPIFY_STORE_DOMAIN")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET")

API_VERSION = "2026-04"
BASE_SUPPLIER_URL = "https://mohasagor.com.bd/api/reseller/product"


def get_shopify_access_token():
    token_url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/oauth/access_token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
    }
    try:
        response = requests.post(token_url, data=payload, timeout=10)
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception as e:
        print(f"Failed to authenticate with Shopify: {e}")
    return None


def normalize_title(title):
    return " ".join((title or "").strip().lower().split())


def compute_prices(item):
    """
    item["price"]      = supplier's Customer/Retail price (সম্ভাব্য বিক্রয় মূল্য)
                          -> this is what we actually charge the customer.
    item["sale_price"]  = supplier's Dropshipper/cost price (ড্রপশিপার প্রাইজ)
                          -> our cost. NEVER shown/charged to customers.

    compare_at_price is a fabricated "regular price" 20-40% above the real
    selling price, just to display a crossed-out discount ("offer").
    """
    retail_price = float(item.get("price") or 0)
    if retail_price <= 0:
        retail_price = float(item.get("sale_price") or 0)

    markup_pct = random.uniform(0.20, 0.40)
    compare_at_price = round((retail_price * (1 + markup_pct)) / 10) * 10

    return retail_price, compare_at_price


def delete_shopify_product(product_id, token):
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
    headers = {"X-Shopify-Access-Token": token}
    for attempt in range(3):
        try:
            res = requests.delete(url, headers=headers, timeout=15)
            if res.status_code in (200, 404):
                print(f"🗑️ Deleted duplicate product id {product_id}")
                return
            elif res.status_code == 429:
                time.sleep(2)
            else:
                print(f"✗ Failed to delete duplicate product {product_id}: {res.text}")
                break
        except Exception as e:
            print(f"⚠️ Network issue deleting product {product_id}, retrying... ({e})")
            time.sleep(5)


def get_existing_catalog_and_cleanup(token):
    all_products = []
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250&fields=id,title,product_type,created_at,variants"
    headers = {"X-Shopify-Access-Token": token}

    print("Scanning full Shopify catalog (categories, duplicates, prices)...")
    while url:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                break

            for product in response.json().get("products", []):
                base_skus = set()
                variants_info = []
                for variant in product.get("variants", []):
                    sku = str(variant.get("sku", ""))
                    variants_info.append({
                        "id": variant.get("id"),
                        "price": variant.get("price"),
                    })
                    if sku:
                        base_skus.add(sku.split('-')[0])

                all_products.append({
                    "id": product.get("id"),
                    "title": product.get("title", ""),
                    "norm_title": normalize_title(product.get("title", "")),
                    "product_type": (product.get("product_type") or "").strip(),
                    "created_at": product.get("created_at") or "",
                    "base_skus": base_skus,
                    "variants": variants_info,
                })

            link_header = response.headers.get("Link")
            url = None
            if link_header:
                for link in link_header.split(","):
                    if 'rel="next"' in link:
                        url = link[link.find("<")+1:link.find(">")]
                        break
        except Exception as e:
            print(f"Network blip while scanning Shopify, continuing... ({e})")
            time.sleep(2)

    print(f"Total products currently in Shopify: {len(all_products)}")

    title_groups = {}
    for p in all_products:
        title_groups.setdefault(p["norm_title"], []).append(p)

    existing_by_sku = {}
    existing_titles = set()
    dup_groups = 0
    dup_deleted = 0

    for norm_title, entries in title_groups.items():
        if not norm_title:
            continue

        if len(entries) > 1:
            dup_groups += 1
            with_category = [e for e in entries if e["product_type"] and e["product_type"].lower() != "uncategorized"]
            pool = with_category if with_category else entries
            keeper = sorted(pool, key=lambda e: e["created_at"])[0]

            for e in entries:
                if e["id"] != keeper["id"]:
                    delete_shopify_product(e["id"], token)
                    dup_deleted += 1
                    time.sleep(0.5)
        else:
            keeper = entries[0]

        existing_titles.add(norm_title)
        for e in entries:
            for base_sku in e["base_skus"]:
                existing_by_sku[base_sku] = {
                    "id": keeper["id"],
                    "product_type": keeper["product_type"],
                    "variants": keeper["variants"],
                }

    print(f"Duplicate title-groups found: {dup_groups} | Extra duplicate products deleted: {dup_deleted}")
    return existing_by_sku, existing_titles


def fetch_supplier_products():
    all_products = []
    page = 1
    supplier_headers = {
        "api-key": DROPSHIP_API_KEY,
        "secret-key": DROPSHIP_SECRET_KEY,
    }

    while True:
        print(f"Fetching page {page} from supplier...")
        try:
            response = requests.get(f"{BASE_SUPPLIER_URL}?page={page}", headers=supplier_headers, timeout=15)
            if response.status_code != 200:
                break

            data = response.json()
            products_data = data.get("products", {})
            items = products_data.get("data", []) if isinstance(products_data, dict) else products_data
            if not items:
                break

            all_products.extend(items)
            last_page = data.get("last_page") or (products_data.get("last_page") if isinstance(products_data, dict) else 1)
            if page >= int(last_page):
                break

            page += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"Network error on page {page}, retrying in 5 seconds... ({e})")
            time.sleep(5)

    print(f"Total products fetched from supplier: {len(all_products)}")
    return all_products


def get_category_name(item):
    candidate_keys = [
        "category", "category_name", "categoryName", "cat_name",
        "main_category", "main_category_name", "product_category",
        "sub_category", "sub_category_name", "subcategory", "type",
    ]

    for key in candidate_keys:
        val = item.get(key)
        if not val:
            continue

        if isinstance(val, str):
            cleaned = val.strip()
            if cleaned:
                return cleaned

        elif isinstance(val, dict):
            for name_key in ("name", "title", "label", "category_name"):
                if val.get(name_key):
                    return str(val[name_key]).strip()

        elif isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                for name_key in ("name", "title", "label"):
                    if first.get(name_key):
                        return str(first[name_key]).strip()

    return "Uncategorized"


def create_shopify_product(item, token, category_name):
    shopify_api_url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products.json"
    shopify_headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    title = item.get("name", "Untitled Product")
    body_html = item.get("details", "")

    retail_price, compare_at_price = compute_prices(item)
    base_sku = str(item.get("product_code") or item.get("id") or "")

    image_urls = set()
    images_payload = []

    thumb = item.get("thumbnail_img")
    if thumb and thumb.startswith("http"):
        image_urls.add(thumb)
        images_payload.append({"src": thumb})

    for img_obj in item.get("product_images", []):
        img_url = img_obj.get("product_image", "")
        if img_url and img_url.startswith("http") and img_url not in image_urls:
            image_urls.add(img_url)
            images_payload.append({"src": img_url})

    variants_payload = []
    raw_variants = item.get("product_variants", [])

    if raw_variants:
        for rv in raw_variants:
            v_name = str(rv.get("variant", "Default")).strip()
            variants_payload.append({
                "option1": v_name,
                "price": str(retail_price),
                "compare_at_price": str(compare_at_price),
                "sku": f"{base_sku}-{v_name}",
                "inventory_management": None
            })
    else:
        variants_payload.append({
            "price": str(retail_price),
            "compare_at_price": str(compare_at_price),
            "sku": base_sku,
            "inventory_management": None
        })

    payload = {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": "Supplier",
            "product_type": category_name,
            "tags": [category_name],
            "images": images_payload,
            "options": [{"name": "Size/Type"}] if raw_variants else [],
            "variants": variants_payload
        }
    }

    for attempt in range(3):
        try:
            res = requests.post(shopify_api_url, json=payload, headers=shopify_headers, timeout=15)
            if res.status_code == 201:
                new_id = res.json().get("product", {}).get("id")
                print(f"✓ Created: {title} [{category_name}] Tk {retail_price} (was Tk {compare_at_price})")
                return new_id
            elif res.status_code == 429:
                print("Rate limited by Shopify. Sleeping for 2 seconds...")
                time.sleep(2)
            else:
                print(f"✗ Failed: {title} | Error: {res.text}")
                break
        except Exception as e:
            print(f"⚠️ Network connection dropped while sending '{title}'. Retrying in 5s... (Attempt {attempt + 1}/3)")
            time.sleep(5)
    return None


def update_shopify_product_category(product_id, category_name, title, token):
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products/{product_id}.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    payload = {"product": {"id": product_id, "product_type": category_name, "tags": category_name}}

    for attempt in range(3):
        try:
            res = requests.put(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                print(f"🔧 Fixed category for '{title}' -> {category_name}")
                return
            elif res.status_code == 429:
                time.sleep(2)
            else:
                print(f"✗ Failed to update category for '{title}': {res.text}")
                break
        except Exception as e:
            print(f"⚠️ Network issue updating '{title}', retrying... ({e})")
            time.sleep(5)


def update_shopify_variant_price(variant_id, price, compare_at_price, token):
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/variants/{variant_id}.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }
    payload = {"variant": {"id": variant_id, "price": str(price), "compare_at_price": str(compare_at_price)}}

    for attempt in range(3):
        try:
            res = requests.put(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                return True
            elif res.status_code == 429:
                time.sleep(2)
            else:
                print(f"✗ Failed to update price for variant {variant_id}: {res.text}")
                return False
        except Exception as e:
            print(f"⚠️ Network issue updating price for variant {variant_id}, retrying... ({e})")
            time.sleep(5)
    return False


def main():
    token = get_shopify_access_token()
    if not token:
        return

    existing_by_sku, existing_titles = get_existing_catalog_and_cleanup(token)
    products = fetch_supplier_products()

    for product in products:
        base_sku = str(product.get("product_code") or product.get("id") or "")
        title = product.get("name", "Untitled Product")
        norm_title = normalize_title(title)
        category_name = get_category_name(product)
        retail_price, compare_at_price = compute_prices(product)

        if base_sku in existing_by_sku:
            info = existing_by_sku[base_sku]
            current_type = info["product_type"]

            needs_category_fix = (not current_type or current_type.lower() == "uncategorized") and category_name != "Uncategorized"
            if needs_category_fix:
                update_shopify_product_category(info["id"], category_name, title, token)
                info["product_type"] = category_name
                time.sleep(0.4)

            existing_variants = info.get("variants", [])
            current_price = None
            if existing_variants and existing_variants[0].get("price") is not None:
                try:
                    current_price = float(existing_variants[0]["price"])
                except (TypeError, ValueError):
                    current_price = None

            needs_price_fix = current_price is None or abs(current_price - retail_price) > 0.5
            if needs_price_fix and retail_price > 0:
                fixed_any = False
                for v in existing_variants:
                    if v.get("id") and update_shopify_variant_price(v["id"], retail_price, compare_at_price, token):
                        fixed_any = True
                    time.sleep(0.4)
                if fixed_any:
                    print(f"💰 Fixed price for '{title}' -> Tk {retail_price} (was showing Tk {current_price})")

            if not needs_category_fix and not needs_price_fix:
                print(f"⏭️ Skipping {title} (Already imported, OK)")

            existing_titles.add(norm_title)
            continue

        if norm_title in existing_titles:
            print(f"⏭️ Skipping {title} (Same product already exists under a different supplier code)")
            continue

        new_id = create_shopify_product(product, token, category_name)
        if new_id:
            existing_by_sku[base_sku] = {"id": new_id, "product_type": category_name, "variants": []}
            existing_titles.add(norm_title)
        time.sleep(0.6)


if __name__ == "__main__":
    main()
