import os
import requests
import json

DROPSHIP_API_KEY = os.environ.get("DROPSHIP_API_KEY")
DROPSHIP_SECRET_KEY = os.environ.get("DROPSHIP_SECRET_KEY")
BASE_SUPPLIER_URL = "https://mohasagor.com.bd/api/reseller/product"

def get_sample_json():
    headers = {
        "api-key": DROPSHIP_API_KEY,
        "secret-key": DROPSHIP_SECRET_KEY,
    }
    
    print("Fetching raw API sample from supplier...\n")
    response = requests.get(f"{BASE_SUPPLIER_URL}?page=1", headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        products_data = data.get("products", {})
        # Extract items
        items = products_data.get("data", []) if isinstance(products_data, dict) else products_data
        
        if items:
            # Print the first 5 products beautifully formatted
            print(json.dumps(items[:5], indent=4, ensure_ascii=False))
        else:
            print("No products found in the response.")
    else:
        print(f"Failed to fetch data: {response.status_code}")

if __name__ == "__main__":
    get_sample_json()
