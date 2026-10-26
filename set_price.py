import os, time, requests, hashlib, math
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}; B=f"https://{DOM}/admin/api/{V}"
def gql(q,v=None):
    for a in range(8):
        r=requests.post(f"{B}/graphql.json",headers=H,json={"query":q,"variables":v or {}},timeout=60)
        if r.status_code==429 or "THROTTLED" in r.text: time.sleep(3+a); continue
        return r.json()
DISCOUNTS=[0.15,0.18,0.20,0.22,0.25,0.28,0.30,0.33,0.35]
d=gql('{ products(first:10, query:"Galaxy Star Projector status:active"){ nodes{ id legacyResourceId title tags variants(first:5){ nodes{ legacyResourceId sku price compareAtPrice } } } } }')
p=[x for x in d["data"]["products"]["nodes"] if "2-in-1" in x["title"].lower() and "12 interchangeable" in x["title"].lower()][0]
code=p["variants"]["nodes"][0]["sku"].split("-")[0]
disc=DISCOUNTS[int(hashlib.md5(code.encode()).hexdigest(),16)%len(DISCOUNTS)]
ca=int(math.ceil(1650/(1-disc)/10)*10)
for v in p["variants"]["nodes"]:
    r=requests.put(f"{B}/variants/{v['legacyResourceId']}.json",headers=H,json={"variant":{"id":int(v["legacyResourceId"]),"price":"1650","compare_at_price":str(ca)}})
    print("variant",v["sku"],r.status_code,"->",r.json().get("variant",{}).get("price"),r.json().get("variant",{}).get("compare_at_price"))
print("tags:",p["tags"])
print("supplier key check:",requests.get("https://mohasagor.com.bd/api/reseller/product?page=1",headers={"api-key":os.environ["DROPSHIP_API_KEY"],"secret-key":os.environ["DROPSHIP_SECRET_KEY"]},timeout=30).status_code)
