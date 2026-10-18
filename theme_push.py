"""Copy the live theme, apply Nogor design changes to the COPY, print a preview link. Live theme is not touched."""
import os, re, json, time, requests, pathlib
DOM = os.environ["SHOPIFY_STORE_DOMAIN"]; V = "2026-04"
DRAFT = "Nogor Design (draft)"
tok = requests.post(f"https://{DOM}/admin/oauth/access_token", data={"grant_type": "client_credentials",
      "client_id": os.environ["SHOPIFY_CLIENT_ID"], "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}, timeout=20).json()["access_token"]
H = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}
B = f"https://{DOM}/admin/api/{V}"

def gql(q, v=None):
    return requests.post(f"{B}/graphql.json", headers=H, json={"query": q, "variables": v or {}}, timeout=60).json()

themes = requests.get(f"{B}/themes.json", headers=H).json()["themes"]
live = [t for t in themes if t["role"] == "main"][0]
print("live theme:", live["id"], live["name"])
draft = next((t for t in themes if t["name"] == DRAFT), None)
if not draft:
    d = gql("""mutation($id: ID!, $name: String){ themeDuplicate(id: $id, name: $name){ newTheme{ id name } userErrors{ field message } } }""",
            {"id": f"gid://shopify/OnlineStoreTheme/{live['id']}", "name": DRAFT})
    print("duplicate:", json.dumps(d)[:400])
    nt = ((d.get("data") or {}).get("themeDuplicate") or {}).get("newTheme")
    if not nt:
        raise SystemExit("could not duplicate theme")
    tid = int(nt["id"].split("/")[-1])
else:
    tid = draft["id"]; print("reusing draft", tid)
for _ in range(60):
    t = requests.get(f"{B}/themes/{tid}.json", headers=H).json()["theme"]
    if not t.get("processing"): break
    time.sleep(5)
print("draft theme:", tid, "processing:", t.get("processing"))

def get(key):
    r = requests.get(f"{B}/themes/{tid}/assets.json", headers=H, params={"asset[key]": key})
    return r.json()["asset"]["value"]

def put(key, value):
    for a in range(5):
        r = requests.put(f"{B}/themes/{tid}/assets.json", headers=H, json={"asset": {"key": key, "value": value}})
        if r.status_code == 429: time.sleep(2); continue
        print("  put", key, r.status_code, "" if r.ok else r.text[:300]); return r.ok

def load_json(s):
    return json.loads(re.sub(r"^\s*/\*.*?\*/", "", s, flags=re.S))

# 1. new snippets/sections
for f in sorted(pathlib.Path("theme_patch").rglob("*.liquid")):
    put(str(f.relative_to("theme_patch")), f.read_text())

# 2. layout hooks
lay = get("layout/theme.liquid")
if "nogor-global-styles" not in lay:
    lay = lay.replace("</head>", "    {% render 'nogor-global-styles' %}\n  </head>", 1)
if "nogor-float" not in lay:
    lay = lay.replace("</body>", "    {% render 'nogor-float' %}\n  </body>", 1)
put("layout/theme.liquid", lay)

# 3. product page: order buttons + trust list after Add to cart
pj = load_json(get("templates/product.json"))
det = next(b for b in pj["sections"]["main"]["blocks"].values() if b["type"] == "_product-details")
if "nogor_trust" not in det["blocks"]:
    det["blocks"]["nogor_trust"] = {"type": "custom-liquid", "settings": {"custom_liquid": "{% render 'nogor-product-trust', product: product %}"}}
    order = det["block_order"]
    bb = next(k for k in order if det["blocks"][k]["type"] == "buy-buttons")
    order.insert(order.index(bb) + 1, "nogor_trust")
put("templates/product.json", json.dumps(pj, ensure_ascii=False, indent=2))

# 4. footer
put("sections/footer-group.json", json.dumps({"type": "footer", "name": "Footer",
    "sections": {"nogor_footer": {"type": "nogor-footer", "settings": {}}}, "order": ["nogor_footer"]}, indent=2))

# 5. announcement
hg = get("sections/header-group.json")
hg2 = hg.replace("Fast delivery across Dhaka", "সারা বাংলাদেশে হোম ডেলিভারি 🚚 · ক্যাশ অন ডেলিভারি")
put("sections/header-group.json", hg2)

# 6. sale badge shows the real percentage
cg = get("blocks/_product-card-gallery.liquid")
cg = cg.replace("{{ 'content.product_badge_sale' | t }}",
    "{%- assign ne_off = product.compare_at_price | minus: product.price | times: 100 | divided_by: product.compare_at_price -%}-{{ ne_off }}%")
put("blocks/_product-card-gallery.liquid", cg)

print("\nPREVIEW:", f"https://nogoressetials.com/?preview_theme_id={tid}")
