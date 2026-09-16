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
    response = requests.post(token_url, data=payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print(f"Failed to authenticate with Shopify: {response.status_code} - {response.text}")
        return None

def fetch_supplier_products():
    all_products = []
    page = 1
    supplier_headers = {
        "api-key": DROPSHIP_API_KEY,
        "secret-key": DROPSHIP_SECRET_KEY,
    }

    while True:
        print(f"Fetching page {page} from supplier...")
        response = requests.get(f"{BASE_SUPPLIER_URL}?page={page}", headers=supplier_headers)
        
        if response.status_code != 200:
            print(f"Error fetching page {page}: {response.status_code}")
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

    print(f"Total products fetched: {len(all_products)}")
    return all_products

def create_shopify_product(item, token):
    shopify_api_url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products.json"
    shopify_headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    title = item.get("name", "Untitled Product")
    body_html = item.get("details", "")
    
    # Category fallback logic
    category_name = item.get("category", "")
    if not category_name:
        category_name = "Uncategorized"

    # Smart Pricing (Utilizing Sale Price vs Regular Price)
    regular_price = float(item.get("price") or 0)
    sale_price = float(item.get("sale_price") or regular_price)
    
    base_sku = str(item.get("product_code") or item.get("id") or "")

    # Clean Image Processing
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

    # Variant & Options Builder
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
        # Default single variant if no sizes/colors exist
        variants_payload.append({
            "price": str(sale_price),
            "compare_at_price": str(regular_price) if regular_price > sale_price else None,
            "sku": base_sku,
            "inventory_management": None
        })

    # Shopify Product Schema
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

    res = requests.post(shopify_api_url, json=payload, headers=shopify_headers)
    if res.status_code == 201:
        print(f"✓ Created: {title} (Variants: {len(variants_payload)})")
    else:
        print(f"✗ Failed: {title} | Error: {res.text}")

def main():
    token = get_shopify_access_token()
    if not token:
        return

    # We removed the duplicate deletion step since it's faster to bulk delete 
    # directly in Shopify before running this clean import.
    products = fetch_supplier_products()
    
    for product in products:
        create_shopify_product(product, token)
        time.sleep(0.6) # Required to respect Shopify API rate limits

if __name__ == "__main__":
    main()
