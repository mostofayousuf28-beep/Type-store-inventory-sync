import os, json, time, requests
from collections import Counter
H = {"api-key": os.environ["DROPSHIP_API_KEY"], "secret-key": os.environ["DROPSHIP_SECRET_KEY"]}
URL = "https://mohasagor.com.bd/api/reseller/product"
TARGETS = {"13320", "13321", "13319", "13318", "13317"}
items = []
page = 1
while True:
    r = requests.get(f"{URL}?page={page}", headers=H, timeout=30)
    if r.status_code != 200:
        print("FAIL page", page, r.status_code, r.text[:200]); break
    d = r.json()
    items += d.get("products") or []
    if page >= int(d.get("last_page") or 1): break
    page += 1
print("fetched pages", page, "items", len(items))
codes = Counter(str(i.get("product_code")) for i in items)
print("duplicate product_codes:", [c for c, n in codes.items() if n > 1][:20])
print("missing code:", sum(1 for i in items if not i.get("product_code")))
print("status:", Counter(str(i.get("status")) for i in items))
print("stock_status:", Counter(str(i.get("stock_status")) for i in items))
pairs = Counter((str(i.get("stock_status")), "0" if i.get("stock") == 0 else ("neg" if (i.get("stock") or 0) < 0 else ("None" if i.get("stock") is None else "pos"))) for i in items)
print("stock_status x stock:", pairs)
print("stock range:", min(i.get("stock") or 0 for i in items), max(i.get("stock") or 0 for i in items))
print("price<=sale_price count:", sum(1 for i in items if (i.get("price") or 0) <= (i.get("sale_price") or 0)))
print("price==0:", sum(1 for i in items if not i.get("price")), "sale_price==0:", sum(1 for i in items if not i.get("sale_price")))
print("variant attrs:", Counter(v.get("attribute") for i in items for v in (i.get("product_variants") or [])).most_common(10))
print("with variants:", sum(1 for i in items if i.get("product_variants")))
print("variant extra keys:", set(k for i in items for v in (i.get("product_variants") or []) for k in v))
print("multi-attribute products:", sum(1 for i in items if len({v.get('attribute') for v in (i.get('product_variants') or [])}) > 1))
names = Counter(" ".join(str(i.get("name","")).lower().split()) for i in items)
print("supplier duplicate names:", sum(1 for n, c in names.items() if c > 1))
print("categories:", len(set(i.get("category") for i in items)), Counter(i.get("category") for i in items).most_common(5))
for i in items:
    if str(i.get("product_code")) in TARGETS:
        j = dict(i); j["details"] = str(j.get("details"))[:60]; j["product_images"] = len(j.get("product_images") or [])
        print("TARGET", json.dumps(j, ensure_ascii=False))
# examples of stock_status non-empty with stock 0, and negative
for cond, label in [(lambda i: i.get("stock_status")=="available" and i.get("stock")==0, "avail&0"), (lambda i: (i.get("stock") or 0) < 0, "neg"), (lambda i: i.get("stock_status") not in ("", "available", None), "other_status")]:
    ex = [ (i.get("product_code"), i.get("stock"), i.get("stock_status"), i.get("status")) for i in items if cond(i)][:5]
    print("EX", label, ex)

# ---- Shopify side ----
dom = os.environ["SHOPIFY_STORE_DOMAIN"]
tok = requests.post(f"https://{dom}/admin/oauth/access_token", data={"grant_type": "client_credentials", "client_id": os.environ["SHOPIFY_CLIENT_ID"], "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}, timeout=20).json().get("access_token")
SH = {"X-Shopify-Access-Token": tok}
V = "2026-04"
sc = requests.get(f"https://{dom}/admin/oauth/access_scopes.json", headers=SH, timeout=20)
print("SCOPES", sc.status_code, [s["handle"] for s in sc.json().get("access_scopes", [])] if sc.ok else sc.text[:200])
loc = requests.get(f"https://{dom}/admin/api/{V}/locations.json", headers=SH, timeout=20)
print("LOCATIONS", loc.status_code, [(l["id"], l["name"], l.get("active")) for l in loc.json().get("locations", [])] if loc.ok else loc.text[:200])
prods = []
url = f"https://{dom}/admin/api/{V}/products.json?limit=250&fields=id,title,status,vendor,product_type,variants,images,options"
while url:
    r = requests.get(url, headers=SH, timeout=30)
    if not r.ok: print("SHOP FAIL", r.status_code); break
    prods += r.json()["products"]
    url = None
    for part in (r.headers.get("Link") or "").split(","):
        if 'rel="next"' in part: url = part[part.find("<")+1:part.find(">")]
print("shopify products:", len(prods))
print("vendor:", Counter(p.get("vendor") for p in prods).most_common(5))
print("status:", Counter(p.get("status") for p in prods))
skus = [v.get("sku") or "" for p in prods for v in p["variants"]]
print("variants:", len(skus), "no sku:", sum(1 for s in skus if not s))
base = Counter()
for p in prods:
    bs = {(v.get("sku") or "").split("-")[0] for v in p["variants"] if v.get("sku")}
    for b in bs: base[b] += 1
print("base skus shared by >1 product:", sum(1 for b, n in base.items() if n > 1))
sup_codes = set(codes)
print("shopify base skus not in supplier:", sum(1 for b in base if b not in sup_codes))
print("supplier codes not in shopify:", sum(1 for c in sup_codes if c not in base))
print("inventory_management:", Counter(str(v.get("inventory_management")) for p in prods for v in p["variants"]))
print("inventory_policy:", Counter(str(v.get("inventory_policy")) for p in prods for v in p["variants"]))
print("non-supplier-looking products (no digit sku):", [(p["id"], p["title"][:40]) for p in prods if not any((v.get("sku") or "")[:1].isdigit() for v in p["variants"])][:10])
ex = prods[0] if prods else {}
print("EX SHOP", json.dumps({"title": ex.get("title"), "options": ex.get("options"), "variants": [{k: v.get(k) for k in ("id","sku","price","compare_at_price","option1","inventory_item_id","inventory_quantity","inventory_management")} for v in ex.get("variants", [])][:3], "images": len(ex.get("images", []))}, ensure_ascii=False))
for p in prods:
    if any((v.get("sku") or "").split("-")[0] in TARGETS for v in p["variants"]):
        print("SHOP TARGET", p["title"], [(v.get("sku"), v.get("price"), v.get("compare_at_price")) for v in p["variants"]])
