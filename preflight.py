import os, requests
dom = os.environ["SHOPIFY_STORE_DOMAIN"]
print("domain:", dom)
r = requests.post(f"https://{dom}/admin/oauth/access_token", data={"grant_type": "client_credentials", "client_id": os.environ["SHOPIFY_CLIENT_ID"], "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}, timeout=20)
print("token HTTP", r.status_code, "" if r.ok else r.text[:300])
tok = r.json().get("access_token") if r.ok else None
if tok:
    H = {"X-Shopify-Access-Token": tok}
    s = requests.get(f"https://{dom}/admin/oauth/access_scopes.json", headers=H, timeout=20)
    print("scopes:", [x["handle"] for x in s.json().get("access_scopes", [])] if s.ok else s.text[:200])
    sh = requests.get(f"https://{dom}/admin/api/2026-04/shop.json", headers=H, timeout=20)
    if sh.ok:
        j = sh.json()["shop"]; print("shop:", j.get("name"), j.get("currency"), j.get("iana_timezone"), j.get("plan_name"))
    else:
        print("shop.json", sh.status_code, sh.text[:200])
    c = requests.get(f"https://{dom}/admin/api/2026-04/products/count.json", headers=H, timeout=20)
    print("product count:", c.text[:100])
