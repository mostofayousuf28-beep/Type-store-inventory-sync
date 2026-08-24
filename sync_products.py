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
    price = str(item.get("reselling_price") or item.get("price") or 0)
    sku = str(item.get("product_code") or item.get("id") or "")
    
    images = []
    
    # Check main product image or thumbnail first if available
    thumb = item.get("thumbnail") or item.get("thumbnail_img")
    if thumb:
        if not thumb.startswith("http"):
            thumb = f"https://mohasagor.com.bd/storage/{thumb.lstrip('/')}"
        images.append({"src": thumb})

    # Process product image array
    for img in item.get("product_image", []):
        img_url = img.get("product_image", "")
        if img_url:
            if not img_url.startswith("http"):
                # Try standard storage path structure
                img_url = f"https://mohasagor.com.bd/storage/{img_url.lstrip('/')}"
            images.append({"src": img_url})

    payload = {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": "Supplier",
            "images": images,
            "variants": [
                {
                    "price": price,
                    "sku": sku,
                    "inventory_management": None
                }
            ]
        }
    }

    res = requests.post(shopify_api_url, json=payload, headers=shopify_headers)
    if res.status_code == 201:
        print(f"✓ Successfully created with images: {title}")
    else:
        print(f"✗ Failed to create {title}: {res.status_code} - {res.text}")

def main():
    token = get_shopify_access_token()
    if not token:
        return

    products = fetch_supplier_products()
    for product in products:
        create_shopify_product(product, token)
        time.sleep(0.6)

if __name__ == "__main__":
    main()
