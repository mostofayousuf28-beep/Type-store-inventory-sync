import os, json, requests
H = {"api-key": os.environ["DROPSHIP_API_KEY"], "secret-key": os.environ["DROPSHIP_SECRET_KEY"]}
URL = "https://mohasagor.com.bd/api/reseller/product"
TARGETS = {"13320", "13321", "13319", "13317"}

def trim(p):
    p = dict(p)
    if isinstance(p.get("details"), str):
        p["details"] = p["details"][:80] + "..."
    return p

r = requests.get(URL + "?page=1", headers=H, timeout=30)
print("HTTP", r.status_code)
d = r.json()
print("TOP-LEVEL KEYS:", list(d.keys()))
prods = d.get("products")
if isinstance(prods, dict):
    print("products is dict, keys:", [k for k in prods.keys() if k != "data"])
    items = prods.get("data", [])
else:
    items = prods or []
print("items on page 1:", len(items))
for k, v in d.items():
    if k != "products":
        print("TOP", k, "=", v)
print("=== FIRST PRODUCT KEYS ===", sorted(items[0].keys()))
found = 0
for it in items:
    if str(it.get("product_code")) in TARGETS:
        print("=== TARGET", it.get("product_code"), "===")
        print(json.dumps(trim(it), ensure_ascii=False, indent=1)[:4000])
        found += 1
# one with variants
for it in items:
    pv = it.get("product_variants") or it.get("product_variant")
    if pv:
        print("=== PRODUCT WITH VARIANTS", it.get("product_code"), "===")
        print(json.dumps(trim(it), ensure_ascii=False, indent=1)[:5000])
        break
print("=== FIRST PRODUCT FULL ===")
print(json.dumps(trim(items[0]), ensure_ascii=False, indent=1)[:4000])
# stock-ish keys across page
keys = set()
for it in items: keys |= set(it.keys())
print("ALL KEYS ON PAGE:", sorted(keys))
# status distribution
from collections import Counter
print("status counts:", Counter(str(it.get("status")) for it in items))
for key in ("stock","quantity","qty","stock_status","in_stock"):
    vals = Counter(str(it.get(key)) for it in items if key in it)
    if vals: print(key, vals.most_common(10))
