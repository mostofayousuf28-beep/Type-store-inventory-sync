import os, time, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None):
    for a in range(8):
        r=requests.post(f"https://{DOM}/admin/api/{V}/graphql.json",headers=H,json={"query":q,"variables":v or {}},timeout=60)
        if r.status_code==429 or "THROTTLED" in r.text: time.sleep(3+a); continue
        return r.json()
d=gql('{ products(first:10, query:"Galaxy Star Projector status:active"){ nodes{ id title tags variants(first:5){ nodes{ sku price compareAtPrice } } } } }')
nodes=[p for p in d["data"]["products"]["nodes"] if "galaxy" in p["title"].lower() and "projector" in p["title"].lower()]
for p in nodes: print("found:",p["title"],[ (v["sku"],v["price"],v["compareAtPrice"]) for v in p["variants"]["nodes"]], p["tags"])
target=[p for p in nodes if "2-in-1" in p["title"].lower() and "12 interchangeable" in p["title"].lower()]
if len(target)!=1:
    raise SystemExit(f"expected exactly 1 match, got {len(target)}")
p=target[0]
codes={v["sku"].split("-")[0] for v in p["variants"]["nodes"]}
H2={"api-key":os.environ["DROPSHIP_API_KEY"],"secret-key":os.environ["DROPSHIP_SECRET_KEY"]}
pg=1
while True:
    j=requests.get(f"https://mohasagor.com.bd/api/reseller/product?page={pg}",headers=H2,timeout=30).json()
    for it in j["products"]:
        if str(it["product_code"]) in codes: print("supplier:",it["product_code"],"retail",it["price"],"cost",it["sale_price"])
    if pg>=j["last_page"]: break
    pg+=1
old=[t for t in p["tags"] if t.lower().startswith("price-")]
if old: gql('mutation($id:ID!,$t:[String!]!){ tagsRemove(id:$id, tags:$t){ userErrors{message} } }',{"id":p["id"],"t":old})
r=gql('mutation($id:ID!){ tagsAdd(id:$id, tags:["price-1650"]){ userErrors{message} } }',{"id":p["id"]})
print("tag added:", r["data"]["tagsAdd"]["userErrors"] or "ok")
time.sleep(5)
