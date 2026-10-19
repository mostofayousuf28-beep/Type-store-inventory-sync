import os, time, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None):
    for a in range(8):
        r=requests.post(f"https://{DOM}/admin/api/{V}/graphql.json",headers=H,json={"query":q,"variables":v or {}},timeout=60)
        if r.status_code==429 or "THROTTLED" in r.text: time.sleep(3+a); continue
        return r.json()
def find(q):
    return gql('query($q:String!){ products(first:5, query:$q){ nodes{ id title priceRangeV2{minVariantPrice{amount}} } } }',{"q":q})["data"]["products"]["nodes"]
out=[p for p in find('tag:best-seller Puja') if 'puja' in p['title'].lower()]
for p in out:
    gql('mutation($id:ID!){ tagsRemove(id:$id, tags:["best-seller"]){ userErrors{message} } }',{"id":p["id"]}); print("removed:",p["title"])
new=[p for p in find('status:active Katan Saree') if 'katan' in p['title'].lower()][:1] or [p for p in find('status:active saree') if 'saree' in p['title'].lower()][:1]
for p in new:
    gql('mutation($id:ID!){ tagsAdd(id:$id, tags:["best-seller"]){ userErrors{message} } }',{"id":p["id"]}); print("added:",p["title"],"| Tk",p["priceRangeV2"]["minVariantPrice"]["amount"])
time.sleep(20)
print([p["title"][:60] for p in gql('{ products(first:50, query:"tag:best-seller"){ nodes{ title } } }')["data"]["products"]["nodes"]])
