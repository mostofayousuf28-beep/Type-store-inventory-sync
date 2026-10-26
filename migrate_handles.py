import os, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok}
r=requests.get(f"https://{DOM}/admin/api/{V}/redirects.json",headers=H,params={"path":"/products/2-in-1-usb-mini-galaxy-star-projector-bedside-night-light-with-360-flexible-design-12-interchangeable-disks-5334"})
print("redirect:",r.json())
print("total redirects:",requests.get(f"https://{DOM}/admin/api/{V}/redirects/count.json",headers=H).json())
