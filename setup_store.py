"""One-time store setup for the new Nogor Essentials Shopify store.

Creates (only if missing): theme images, smart collections, main menu, contact page, redirect.
Safe to run more than once.
"""
import os, re, sys, time, json, requests

DOM = os.environ["SHOPIFY_STORE_DOMAIN"]
V = "2026-04"
OLD_SITE = "https://nogoressetials.com"
SUPPLIER_URL = "https://mohasagor.com.bd/api/reseller/product"

IMAGES = [
    "Logo_d1854561-337c-47b6-a385-d34f3019ec20.png",
    "Untitled_design.png",
    "mobile.png",
    "2_25d223b9-65ad-4c58-99c2-b15971f5c391.png",
    "3_ad7c6629-a1f5-492d-bd9f-7af4f9f662c1.png",
    "4_66214f12-71a8-4a1a-941a-baba90cc5658.png",
    "5_e007ba26-9096-4cee-a625-fc4bd8ab5262.png",
    "6_ba969363-9c5a-445e-bf40-d17c8811915a.png",
    "7_d741d369-e493-4f5a-8cad-8deb4c971d62.png",
    "8_01bc0f65-2468-4bc5-b216-50e5e86b2641.png",
    "9_38781058-51e7-49a9-a11f-8ab9008fc8a9.png",
]

# theme collection handle -> title (order = menu order)
CATEGORY_COLLECTIONS = [
    ("gadgets-and-electronics", "Gadgets and Electronics"),
    ("home-and-lifestyle", "Home and Lifestyle"),
    ("mens-fashion", "Men's Fashion"),
    ("womens-fashion", "Women's Fashion"),
    ("kids-zone", "Kids Zone"),
    ("foods", "Foods"),
    ("customize-and-gift", "Customize and Gift"),
    ("others", "Others"),
]

tok = requests.post(f"https://{DOM}/admin/oauth/access_token", data={
    "grant_type": "client_credentials", "client_id": os.environ["SHOPIFY_CLIENT_ID"],
    "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}, timeout=20).json()["access_token"]
H = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}


def rest(method, path, **kw):
    for a in range(5):
        r = requests.request(method, f"https://{DOM}/admin/api/{V}{path}", headers=H, timeout=40, **kw)
        if r.status_code == 429:
            time.sleep(2); continue
        return r
    return r


def gql(q, v=None):
    for a in range(5):
        r = requests.post(f"https://{DOM}/admin/api/{V}/graphql.json", headers=H, json={"query": q, "variables": v or {}}, timeout=40)
        b = r.json()
        if b.get("errors") and "THROTTLED" in json.dumps(b["errors"]):
            time.sleep(3); continue
        if b.get("errors"):
            print("GQL ERROR", b["errors"]); return None
        return b["data"]


def slug(s):
    s = s.lower().replace("&", "and").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


print("scopes:", [x["handle"] for x in requests.get(f"https://{DOM}/admin/oauth/access_scopes.json", headers=H, timeout=20).json().get("access_scopes", [])])

# ------------------------------------------------------------------ 1. images
print("\n== images")
existing = set()
d = gql('{ files(first: 250) { nodes { ... on MediaImage { image { url } } ... on GenericFile { url } } } }')
for n in (d or {}).get("files", {}).get("nodes", []):
    u = (n.get("image") or {}).get("url") or n.get("url") or ""
    existing.add(u.split("/")[-1].split("?")[0])
todo = [f for f in IMAGES if f not in existing]
print("already there:", len(IMAGES) - len(todo), "to copy:", len(todo))
for f in todo:
    src = f"{OLD_SITE}/cdn/shop/files/{f}"
    chk = requests.head(src, timeout=20, allow_redirects=True)
    if chk.status_code != 200:
        print("  ✗ not reachable on old site:", f, chk.status_code); continue
    d = gql("""mutation($f:[FileCreateInput!]!){ fileCreate(files:$f){ files{ id fileStatus } userErrors{ field message } } }""",
            {"f": [{"originalSource": src, "filename": f, "contentType": "IMAGE"}]})
    errs = (d or {}).get("fileCreate", {}).get("userErrors")
    print("  ", "✗" if errs else "✓", f, errs or "")
time.sleep(10)
d = gql('{ files(first: 250) { nodes { fileStatus ... on MediaImage { image { url } } } } }')
for n in (d or {}).get("files", {}).get("nodes", []):
    print("   file:", n.get("fileStatus"), ((n.get("image") or {}).get("url") or "").split("/")[-1].split("?")[0])

# ------------------------------------------------------------------ 2. collections
print("\n== supplier categories")
sh = {"api-key": os.environ["DROPSHIP_API_KEY"], "secret-key": os.environ["DROPSHIP_SECRET_KEY"]}
cats, page = {}, 1
while True:
    r = requests.get(f"{SUPPLIER_URL}?page={page}", headers=sh, timeout=30).json()
    for p in r.get("products") or []:
        c = (p.get("category") or "").strip() or "Uncategorized"
        cats[c] = cats.get(c, 0) + 1
    if page >= int(r.get("last_page") or 1): break
    page += 1
for c, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"  {n:5d}  {c}  -> {slug(c)}")

print("\n== collections")
have = {c["handle"]: c for c in rest("GET", "/smart_collections.json?limit=250").json().get("smart_collections", [])}
have.update({c["handle"]: c for c in rest("GET", "/custom_collections.json?limit=250").json().get("custom_collections", [])})

wanted = []
matched = set()
for handle, title in CATEGORY_COLLECTIONS:
    sup = [c for c in cats if slug(c) == handle]
    matched.update(sup)
    wanted.append((handle, title, sup))
extra = [c for c in cats if c not in matched and c != "Uncategorized"]
for c in extra:
    wanted.append((slug(c), c, [c]))
    print("  extra supplier category gets its own collection:", c)

coll_ids = {}
for handle, title, sup in wanted:
    if handle in have:
        coll_ids[handle] = have[handle]["id"]; print("  exists:", handle); continue
    if not sup:
        print("  ⚠ no supplier category for", handle, "- creating empty-rule collection skipped")
        # create a manual (custom) collection so the menu link works
        r = rest("POST", "/custom_collections.json", json={"custom_collection": {"title": title, "handle": handle, "published": True}})
    else:
        rules = [{"column": "type", "relation": "equals", "condition": c} for c in sup]
        r = rest("POST", "/smart_collections.json", json={"smart_collection": {
            "title": title, "handle": handle, "rules": rules, "disjunctive": True,
            "sort_order": "created-desc", "published": True}})
    ok = r.status_code in (200, 201)
    body = r.json()
    cid = (body.get("smart_collection") or body.get("custom_collection") or {}).get("id")
    coll_ids[handle] = cid
    print("  ", "✓" if ok else "✗", handle, title, sup, "" if ok else r.text[:200])

for handle, title, sort in [("new-arrival", "New Arrivals", "created-desc"), ("best-seller", "Best Seller", "best-selling")]:
    if handle in have:
        coll_ids[handle] = have[handle]["id"]; print("  exists:", handle); continue
    r = rest("POST", "/smart_collections.json", json={"smart_collection": {
        "title": title, "handle": handle, "rules": [{"column": "vendor", "relation": "equals", "condition": "Supplier"}],
        "sort_order": sort, "published": True}})
    coll_ids[handle] = (r.json().get("smart_collection") or {}).get("id")
    print("  ", "✓" if r.status_code == 201 else "✗", handle, "" if r.status_code == 201 else r.text[:200])

# ------------------------------------------------------------------ 3. contact page
print("\n== pages")
pages = {p["handle"]: p for p in rest("GET", "/pages.json?limit=250").json().get("pages", [])}
print("  existing pages:", list(pages))
if "contact" not in pages:
    r = rest("POST", "/pages.json", json={"page": {"title": "Contact", "handle": "contact", "template_suffix": "contact", "body_html": "", "published": True}})
    pages["contact"] = r.json().get("page", {})
    print("  ", "✓" if r.status_code == 201 else "✗", "contact page", "" if r.status_code == 201 else r.text[:200])
elif pages["contact"].get("template_suffix") != "contact":
    rest("PUT", f"/pages/{pages['contact']['id']}.json", json={"page": {"id": pages["contact"]["id"], "template_suffix": "contact"}})
    print("  contact page set to contact template")

# ------------------------------------------------------------------ 4. main menu
print("\n== menu")
def cgid(h): return f"gid://shopify/Collection/{coll_ids[h]}" if coll_ids.get(h) else None
children = []
for h, t in [("new-arrival", "New Arrivals"), ("best-seller", "Best Seller")] + [(h, t) for h, t, _ in wanted]:
    if cgid(h):
        children.append({"title": t, "type": "COLLECTION", "resourceId": cgid(h)})
items = [
    {"title": "Home", "type": "FRONTPAGE", "url": "/"},
    {"title": "Categories", "type": "COLLECTIONS", "url": "/collections", "items": children},
    {"title": "Catalog", "type": "CATALOG", "url": "/collections/all"},
]
if pages.get("contact", {}).get("id"):
    items.append({"title": "Contact", "type": "PAGE", "resourceId": f"gid://shopify/Page/{pages['contact']['id']}"})
d = gql('{ menus(first: 20) { nodes { id handle title } } }')
menus = {m["handle"]: m for m in (d or {}).get("menus", {}).get("nodes", [])}
print("  existing menus:", list(menus))
if "main-menu" in menus:
    d = gql("""mutation($id:ID!,$t:String!,$h:String,$i:[MenuItemUpdateInput!]!){ menuUpdate(id:$id,title:$t,handle:$h,items:$i){ menu{ id handle } userErrors{ field message } } }""",
            {"id": menus["main-menu"]["id"], "t": "Main menu", "h": "main-menu", "i": items})
    print("  menuUpdate:", d)
else:
    d = gql("""mutation($t:String!,$h:String!,$i:[MenuItemCreateInput!]!){ menuCreate(title:$t,handle:$h,items:$i){ menu{ id handle } userErrors{ field message } } }""",
            {"t": "Main menu", "h": "main-menu", "i": items})
    print("  menuCreate:", d)

# ------------------------------------------------------------------ 5. redirect (theme button links to /collections/new-arrivals)
print("\n== redirect")
r = rest("GET", "/redirects.json?path=/collections/new-arrivals")
if not r.json().get("redirects"):
    r = rest("POST", "/redirects.json", json={"redirect": {"path": "/collections/new-arrivals", "target": "/collections/new-arrival"}})
    print("  ", r.status_code, r.text[:150])
else:
    print("  exists")

print("\n== product count:", rest("GET", "/products/count.json").text)
print("== themes:", [(t["name"], t["role"]) for t in rest("GET", "/themes.json").json().get("themes", [])])
