import os, json, requests, re
from collections import Counter, defaultdict
H={"api-key":os.environ["DROPSHIP_API_KEY"],"secret-key":os.environ["DROPSHIP_SECRET_KEY"]}
items=[];p=1
while True:
    d=requests.get(f"https://mohasagor.com.bd/api/reseller/product?page={p}",headers=H,timeout=30).json()
    items+=d["products"]
    if p>=d["last_page"]: break
    p+=1
norm=lambda s:" ".join((s or "").lower().split())
g=defaultdict(list)
for it in items: g[norm(it["name"])].append(it)
multi=[v for v in g.values() if len(v)>1]
print("groups>1:",len(multi),"products in them:",sum(len(v) for v in multi),"max size:",max(len(v) for v in multi))
print("size dist:",Counter(len(v) for v in multi).most_common(8))
print("groups w/ any member having size variants:",sum(1 for v in multi if any(x.get("product_variants") for x in v)))
print("groups w/ differing price:",sum(1 for v in multi if len({x["price"] for x in v})>1))
print("groups w/ differing category:",sum(1 for v in multi if len({x["category"] for x in v})>1))
print("groups w/ differing details:",sum(1 for v in multi if len({x.get("details") for x in v})>1))
print("variant attr mix in group:",sum(1 for v in multi if len({vv.get("attribute") for x in v for vv in (x.get("product_variants") or [])})>1))
big=sorted(multi,key=len,reverse=True)[:3]
for v in big: print("BIG",len(v),v[0]["name"][:60],[x["product_code"] for x in v][:12])
# details samples
import random; random.seed(3)
for it in random.sample(items,7):
    print("\n=== DETAILS",it["product_code"],"len",len(it.get("details") or ""))
    print(repr((it.get("details") or "")[:700]))
print("\nhas <p>:",sum(1 for i in items if "<p" in (i.get("details") or "")),"has <br:",sum(1 for i in items if "<br" in (i.get("details") or "")),"has \\n:",sum(1 for i in items if "\n" in (i.get("details") or "")),"has <ul:",sum(1 for i in items if "<ul" in (i.get("details") or "")),"plain(no tags):",sum(1 for i in items if "<" not in (i.get("details") or "")))
print("video:",sum(1 for i in items if i.get("video_url")))
