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

def get_existing_shopify_skus(token):
    """Fetches all existing product SKUs from Nogor Essentials to prevent duplicates."""
    existing_skus = set()
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}/products.json?limit=250&fields=variants"
    headers = {"X-Shopify-Access-Token": token}
    
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Error fetching Shopify products: {response.status_code} - {response.text}")
            break
        
        # Add all found SKUs to our set
        for product in response.json().get("products", []):
            for variant in product.get("variants", []):
                sku = variant.get("sku")
                if sku:
                    existing_skus.add(str(sku))
        
        # Handle Shopify's cursor-based pagination for larger catalogs
        link_header = response.headers.get("Link")
        url = None
        if link_header:
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link[link.find("<")+1:link.find(">")]
                    break
    
    print(f"Found {len(existing_skus)} existing products in Shopify.")
    return existing_skus

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
    
    category_name = ""
    cat = item.get("category")
    if isinstance(cat, dict):
        category_name = cat.get("name", "")
    elif isinstance(cat, str):
        category_name = cat
    
    if not category_name:
        category_name = item.get("category_name", "") or item.get("type", "")

    images = []
    
    thumb = item.get("thumbnail") or item.get("thumbnail_img")
    if thumb:
        if not thumb.startswith("http"):
            thumb = f"https://mohasagor.com.bd/storage/{thumb.lstrip('/')}"
        images.append({"src": thumb})

    for img in item.get("product_image", []):
        img_url = img.get("product_image", "")
        if img_url:
            if not img_url.startswith("http"):
                img_url = f"https://mohasagor.com.bd/storage/{img_url.lstrip('/')}"
            images.append({"src": img_url})

    payload = {
        "product": {
            "title": title,
            "body_html": body_html,
            "vendor": "Supplier",
            "product_type": category_name,
            "tags": [category_name] if category_name else [],
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
        print(f"✓ Successfully created with category '{category_name}': {title}")
    else:
        print(f"✗ Failed to create {title}: {res.status_code} - {res.text}")

def main():
    token = get_shopify_access_token()
    if not token:
        return

    # 1. Fetch SKUs already in your store
    existing_skus = get_existing_shopify_skus(token)
    
    # 2. Fetch all products from supplier
    products = fetch_supplier_products()
    
    # 3. Loop and create ONLY if SKU isn't in your store
    for product in products:
        sku = str(product.get("product_code") or product.get("id") or "")
        
        # Check if the product already exists
        if sku in existing_skus:
            print(f"⏭️ Skipping duplicate: {product.get('name', 'Product')} (SKU: {sku}) already exists.")
            continue
            
        create_shopify_product(product, token)
        time.sleep(0.6)

if __name__ == "__main__":
    main()
