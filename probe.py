import os, time, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok}
print("scopes:",[x["handle"] for x in requests.get(f"https://{DOM}/admin/oauth/access_scopes.json",headers=H).json().get("access_scopes",[])])
c0=requests.get(f"https://{DOM}/admin/api/{V}/products/count.json",headers=H).json()["count"]
time.sleep(60)
c1=requests.get(f"https://{DOM}/admin/api/{V}/products/count.json",headers=H).json()["count"]
print("count", c0, "-> 60s later", c1, "rate/min", c1-c0)
