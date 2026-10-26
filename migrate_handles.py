"""Give every active supplier product the URL /products/<code> (code = number at the end of the title).
Old URLs keep working through automatic redirects. Safe to run more than once."""
import os, re, time, json, threading, requests
from concurrent.futures import ThreadPoolExecutor
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None):
    for a in range(12):
        try:
            r=requests.post(f"https://{DOM}/admin/api/{V}/graphql.json",headers=H,json={"query":q,"variables":v or {}},timeout=60)
        except Exception as e:
            time.sleep(3+a); continue
        if r.status_code==429 or "THROTTLED" in r.text or r.status_code>=500: time.sleep(min(2+a*2,20)); continue
        j=r.json()
        t=(j.get("extensions") or {}).get("cost",{}).get("throttleStatus",{})
        if t and t.get("currentlyAvailable",1000)<200: time.sleep(2)
        return j
    return {}
prods=[]; cur=None
while True:
    d=gql('query($c:String){ products(first:250, after:$c, query:"vendor:Supplier status:active"){ pageInfo{hasNextPage endCursor} nodes{ id handle title } } }',{"c":cur})
    pd=d["data"]["products"]; prods+=pd["nodes"]
    if not pd["pageInfo"]["hasNextPage"]: break
    cur=pd["pageInfo"]["endCursor"]
print("active supplier products:",len(prods))
todo=[]; nocode=[]; seen={}
for p in prods:
    m=re.search(r"-\s*(\d{3,7})\s*$",p["title"])
    if not m: nocode.append(p["title"]); continue
    code=m.group(1)
    if code in seen: print("  duplicate code",code,p["title"][:50],"|",seen[code][:50]); continue
    seen[code]=p["title"]
    if p["handle"]!=code: todo.append((p["id"],code,p["title"]))
print("to change:",len(todo),"| already short:",len(prods)-len(todo)-len(nocode),"| no code in title:",len(nocode), nocode[:5])
lock=threading.Lock(); done=[0]; errs=[]
def run(job):
    pid,code,title=job
    d=gql('mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ handle } userErrors{ field message } } }',{"p":{"id":pid,"handle":code,"redirectNewHandle":True}})
    pu=(d.get("data") or {}).get("productUpdate") or {}
    with lock:
        done[0]+=1
        if pu.get("userErrors") or not pu.get("product"): errs.append((code,title[:40],pu.get("userErrors") or d.get("errors")))
        elif pu["product"]["handle"]!=code: errs.append((code,title[:40],"got "+pu["product"]["handle"]))
        if done[0]%300==0: print("  ...",done[0],"/",len(todo))
with ThreadPoolExecutor(max_workers=4) as ex: list(ex.map(run,todo))
print("done:",done[0],"errors:",len(errs)); [print("  ",e) for e in errs[:20]]
d=gql('{ productByHandle(handle:"5334"){ title handle } }'); print("check 5334:",d.get("data"))
