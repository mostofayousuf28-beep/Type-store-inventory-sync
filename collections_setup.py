"""New Arrivals = products tagged new-arrival (sync keeps this on the newest items).
Best Seller = products tagged best-seller, ordered by real sales. Until there are sales, a varied hand-picked
set is tagged here (a few from each main category, not the same items as New Arrivals)."""
import os, json, time, requests
DOM = os.environ["SHOPIFY_STORE_DOMAIN"]; V = "2026-04"
tok = requests.post(f"https://{DOM}/admin/oauth/access_token", data={"grant_type": "client_credentials",
      "client_id": os.environ["SHOPIFY_CLIENT_ID"], "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"]}, timeout=20).json()["access_token"]
H = {"X-Shopify-Access-Token": tok, "Content-Type": "application/json"}
B = f"https://{DOM}/admin/api/{V}"

def gql(q, v=None):
    for a in range(6):
        r = requests.post(f"{B}/graphql.json", headers=H, json={"query": q, "variables": v or {}}, timeout=60).json()
        if "THROTTLED" in json.dumps(r.get("errors", "")):
            time.sleep(3); continue
        return r

smart = {c["handle"]: c for c in requests.get(f"{B}/smart_collections.json?limit=250", headers=H).json()["smart_collections"]}
for handle, tag, sort in [("new-arrival", "new-arrival", "created-desc"), ("best-seller", "best-seller", "best-selling")]:
    c = smart.get(handle)
    if not c:
        print("missing collection", handle); continue
    r = requests.put(f"{B}/smart_collections/{c['id']}.json", headers=H, json={"smart_collection": {
        "id": c["id"], "rules": [{"column": "tag", "relation": "equals", "condition": tag}], "disjunctive": False, "sort_order": sort}})
    print("collection", handle, "->", tag, r.status_code, "" if r.ok else r.text[:200])

already = gql('{ productsCount(query: "tag:best-seller status:active") { count } }')["data"]["productsCount"]["count"]
print("already tagged best-seller:", already)
import sys
if "--retag" in sys.argv:
    old = gql('{ products(first: 50, query: "tag:best-seller") { nodes { id } } }')["data"]["products"]["nodes"]
    for p in old:
        gql("""mutation($id: ID!){ tagsRemove(id: $id, tags: ["best-seller"]) { userErrors { message } } }""", {"id": p["id"]})
    already = 0
if already < 8:
    picks_per_cat = [("Gadgets & Electronics", 3), ("Home & Lifestyle", 3), ("Men's Fashion", 2), ("Women's Fashion", 2),
                     ("Winter", 1), ("Kids Zone", 1)]
    chosen = []
    for cat, n in picks_per_cat:
        q = 'product_type:"' + cat.replace('"', '') + '" status:active vendor:Supplier -tag:new-arrival -tag:merged'
        d = gql("""query($q: String!){ products(first: 60, query: $q, sortKey: CREATED_AT, reverse: true) {
                   nodes { id title variantsCount { count } mediaCount { count } descriptionHtml
                           priceRangeV2 { minVariantPrice { amount } } } } }""", {"q": q})
        nodes = (d.get("data") or {}).get("products", {}).get("nodes", [])
        def score(p):
            price = float(p["priceRangeV2"]["minVariantPrice"]["amount"])
            s = 0
            s += 3 if "<iframe" in (p["descriptionHtml"] or "") else 0          # supplier made a video for it
            s += 2 if p["variantsCount"]["count"] > 1 else 0                     # several designs / sizes
            s += min(p["mediaCount"]["count"], 6) * 0.5                         # good photos
            s += 2 if 400 <= price <= 3000 else 0                               # typical impulse price range
            return s
        brands = ("rolex", "hublot", "mercedes", "gucci", "louis", "apple", "samsung", "nike", "adidas", "cartier", "omega", "casio", "iphone")
        nodes = [p for p in nodes if not any(b in p["title"].lower() for b in brands)]
        best = sorted(nodes, key=score, reverse=True)[:n]
        print(" ", cat, "->", [p["title"][:50] for p in best])
        chosen += [p["id"] for p in best]
    for pid in chosen:
        r = gql("""mutation($id: ID!){ tagsAdd(id: $id, tags: ["best-seller"]) { userErrors { message } } }""", {"id": pid})
        errs = (r.get("data") or {}).get("tagsAdd", {}).get("userErrors")
        if errs: print("  tag error", errs)
    print("tagged best-seller:", len(chosen))
