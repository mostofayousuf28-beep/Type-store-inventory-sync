import os, time, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
print("scopes:",[x["handle"] for x in requests.get(f"https://{DOM}/admin/oauth/access_scopes.json",headers=H).json().get("access_scopes",[])])
c0=requests.get(f"https://{DOM}/admin/api/{V}/products/count.json",headers=H).json()
imgs=["https://mohasagor.com.bd/public/storage/images/products/4BQ47gb7HC1anqjNVtyUAhgBukNWBFcYKXCXDIyj.png","https://mohasagor.com.bd/public/storage/images/products/MpLieZnq0evEREUoIqZj70ENzeyFLlkpKJLxtjgN.jpg"]
for label,images in [("with 2 images",[{"src":u} for u in imgs]),("no images",[])]:
    t=time.time()
    r=requests.post(f"https://{DOM}/admin/api/{V}/products.json",headers=H,json={"product":{"title":"ZZ probe "+label,"status":"draft","vendor":"Probe","images":images,"variants":[{"price":"1","sku":"PROBE"}]}},timeout=120)
    dt=time.time()-t
    print(label, r.status_code, f"{dt:.1f}s", r.headers.get("X-Shopify-Shop-Api-Call-Limit"), r.text[:200] if r.status_code!=201 else "")
    if r.status_code==201:
        pid=r.json()["product"]["id"]; requests.delete(f"https://{DOM}/admin/api/{V}/products/{pid}.json",headers=H)
for u in imgs:
    t=time.time(); rr=requests.get(u,timeout=60); print("supplier image fetch",rr.status_code,len(rr.content)//1024,"KB",f"{time.time()-t:.1f}s")
time.sleep(30)
c1=requests.get(f"https://{DOM}/admin/api/{V}/products/count.json",headers=H).json()
print("count",c0,"-> 30s later",c1)
