import os
import time
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

def get_existing_shopify_skus(token):
    """Fetches all existing base SKUs to allow safe resuming."""
    existing_base_skus = set()
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250&fields=variants"
    headers = {"X-Shopify-Access-Token": token}
    
    print("Scanning Shopify to see what is already imported (so we can skip them)...")
    while url:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                break
            
            for product in response.json().get("products", []):
                for variant in product.get("variants", []):
                    sku = str(variant.get("sku", ""))
                    if sku:
                        # Grab the base SKU (before any dash for size/color variants)
                        base_sku = sku.split('-')[0]
                        existing_base_skus.add(base_sku)
            
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
            
    print(f"Found {len(existing_base_skus)} unique products already in Shopify. Ready to resume!")
    return existing_base_skus

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

def create_shopify_product(item, token):
    shopify_api_url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products.json"
    shopify_headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    title = item.get("name", "Untitled Product")
    body_html = item.get("details", "")
    category_name = item.get("category", "")
    if not category_name:
        category_name = "Uncategorized"

    regular_price = float(item.get("price") or 0)
    sale_price = float(item.get("sale_price") or regular_price)
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
                "price": str(sale_price),
                "compare_at_price": str(regular_price) if regular_price > sale_price else None,
                "sku": f"{base_sku}-{v_name}",
                "inventory_management": None
            })
    else:
        variants_payload.append({
            "price": str(sale_price),
            "compare_at_price": str(regular_price) if regular_price > sale_price else None,
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

    # RETRY LOGIC: Try 3 times before giving up
    for attempt in range(3):
        try:
            res = requests.post(shopify_api_url, json=payload, headers=shopify_headers, timeout=15)
            if res.status_code == 201:
                print(f"✓ Created: {title}")
                return # Success! Exit the retry loop
            elif res.status_code == 429:
                print("Rate limited by Shopify. Sleeping for 2 seconds...")
                time.sleep(2)
            else:
                print(f"✗ Failed: {title} | Error: {res.text}")
                break # If it's a structural error (like bad data), don't retry
        except Exception as e:
            print(f"⚠️ Network connection dropped while sending '{title}'. Retrying in 5s... (Attempt {attempt + 1}/3)")
            time.sleep(5)

def main():
    token = get_shopify_access_token()
    if not token:
        return

    # 1. Fetch SKUs already synced successfully
    existing_skus = get_existing_shopify_skus(token)
    
    # 2. Fetch catalog
    products = fetch_supplier_products()
    
    # 3. Resume sync
    for product in products:
        base_sku = str(product.get("product_code") or product.get("id") or "")
        
        if base_sku in existing_skus:
            print(f"⏭️ Skipping {product.get('name')} (Already imported)")
            continue
            
        create_shopify_product(product, token)
        time.sleep(0.6) # Standard Shopify throttle

if __name__ == "__main__":
    main()
