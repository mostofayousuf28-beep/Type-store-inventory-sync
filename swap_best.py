import os, json, time, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None):
    for a in range(8):
        r=requests.post(f"https://{DOM}/admin/api/{V}/graphql.json",headers=H,json={"query":q,"variables":v or {}},timeout=60)
        if r.status_code==429 or "THROTTLED" in r.text: time.sleep(3+a); continue
        return r.json()
INTIMATE=("bra","panty","panties","underwear","lingerie","maternity","bikini","nighty","inner","pad","sanitary","brief")
BRANDS=("rolex","hublot","mercedes","gucci","louis","apple","samsung","nike","adidas","cartier","omega","casio","iphone","chanel","dior","zara")
cur=gql('{ products(first: 50, query: "tag:best-seller") { nodes { id title productType } } }')["data"]["products"]["nodes"]
print("current best-seller:"); [print("  ",p["productType"],"|",p["title"][:70]) for p in cur]
bad=[p for p in cur if any(w in p["title"].lower().replace("-"," ").split() or w in p["title"].lower() for w in ("bra ","maternity","panty","underwear","lingerie"))]
for p in bad:
    gql('mutation($id:ID!){ tagsRemove(id:$id, tags:["best-seller"]){ userErrors{message} } }',{"id":p["id"]})
    print("removed:",p["title"][:70])
q='product_type:"Women\'s Fashion" status:active vendor:Supplier -tag:new-arrival -tag:best-seller'
d=gql("""query($q:String!){ products(first:120, query:$q, sortKey:CREATED_AT, reverse:true){ nodes{ id title variantsCount{count} mediaCount{count} descriptionHtml priceRangeV2{minVariantPrice{amount}} } } }""",{"q":q})
nodes=d["data"]["products"]["nodes"]
def ok(p):
    t=" "+p["title"].lower()+" "
    return not any((" "+w+" ") in t or (" "+w) in t.split("-")[0] for w in INTIMATE) and not any(b in t for b in BRANDS)
nodes=[p for p in nodes if ok(p)]
def score(p):
    price=float(p["priceRangeV2"]["minVariantPrice"]["amount"]); t=p["title"].lower()
    s=0
    s+=3 if "<iframe" in (p["descriptionHtml"] or "") else 0
    s+=2 if p["variantsCount"]["count"]>1 else 0
    s+=min(p["mediaCount"]["count"],6)*0.5
    s+=2 if 500<=price<=2500 else 0
    s+=3 if any(k in t for k in ("three piece","3 piece","three-piece","kurti","abaya","borka","burqa","khimar","hijab","saree","shari","gown","frock","dress","handbag","bag","tops","kameez","salwar","palazzo")) else 0
    return s
ranked=sorted(nodes,key=score,reverse=True)
picks=[]; kinds=set()
for p in ranked:
    t=p["title"].lower()
    kind=next((k for k in ("three piece","kurti","abaya","borka","khimar","hijab","saree","gown","dress","bag","tops","palazzo") if k in t),t.split()[0])
    if kind in kinds: continue
    picks.append(p); kinds.add(kind)
    if len(picks)==len(bad) or len(picks)==2: break
for p in picks:
    gql('mutation($id:ID!){ tagsAdd(id:$id, tags:["best-seller"]){ userErrors{message} } }',{"id":p["id"]})
    print("added:",p["title"][:80],"| Tk",p["priceRangeV2"]["minVariantPrice"]["amount"])
print("top candidates:",[p["title"][:40] for p in ranked[:8]])
