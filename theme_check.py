import os, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
r=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20)
print("shopify token:", r.status_code)
if r.ok:
    H={"X-Shopify-Access-Token":r.json()["access_token"]}
    print("products:", requests.get(f"https://{DOM}/admin/api/{V}/products/count.json",headers=H).text)
    print("domain:", requests.get(f"https://{DOM}/admin/api/{V}/shop.json",headers=H).json()["shop"].get("domain"))
s=requests.get("https://mohasagor.com.bd/api/reseller/product?page=1",headers={"api-key":os.environ["DROPSHIP_API_KEY"],"secret-key":os.environ["DROPSHIP_SECRET_KEY"]},timeout=30)
print("supplier:", s.status_code, "total" , (s.json().get("total") if s.ok else s.text[:150]))
