import os, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}; B=f"https://{DOM}/admin/api/{V}"
th=requests.get(f"{B}/themes.json",headers=H).json()["themes"]
d=next(t for t in th if t["name"]=="Nogor Design (draft)")
r=requests.put(f"{B}/themes/{d['id']}.json",headers=H,json={"theme":{"id":d["id"],"role":"main","name":"Nogor Design"}})
print("publish:",r.status_code,r.text[:200])
print([(t["name"],t["role"]) for t in requests.get(f"{B}/themes.json",headers=H).json()["themes"]])
