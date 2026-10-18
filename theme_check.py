import os, json, requests
DOM=os.environ["SHOPIFY_STORE_DOMAIN"]; V="2026-04"
tok=requests.post(f"https://{DOM}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":os.environ["SHOPIFY_CLIENT_ID"],"client_secret":os.environ["SHOPIFY_CLIENT_SECRET"]},timeout=20).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None): return requests.post(f"https://{DOM}/admin/api/{V}/graphql.json",headers=H,json={"query":q,"variables":v or {}}).json()
themes=requests.get(f"https://{DOM}/admin/api/{V}/themes.json",headers=H).json()["themes"]
for t in themes: print("theme", t["id"], t["name"], t["role"], t.get("processing"))
actual=[t for t in themes if t["name"]=="Actual"]
if actual:
    a=actual[0]
    for key in ["config/settings_data.json","templates/index.json","sections/nogor-hero.liquid"]:
        r=requests.get(f"https://{DOM}/admin/api/{V}/themes/{a['id']}/assets.json",headers=H,params={"asset[key]":key})
        v=(r.json().get("asset") or {}).get("value","")
        print(key, r.status_code, len(v), "| logo ref:", "Logo_d1854561" in v, "| hero ref:", "Untitled_design" in v)
# image files present?
for name in ["Logo_d1854561","Untitled_design","mobile","2_25d223b9","9_38781058"]:
    d=gql('query($q:String){ files(first:5, query:$q){ nodes{ fileStatus alt ... on MediaImage { image { url } } } } }',{"q":f"filename:{name}*"})
    print("file", name, [(n.get("fileStatus"), ((n.get("image") or {}).get("url") or "").split("/")[-1].split("?")[0]) for n in d.get("data",{}).get("files",{}).get("nodes",[])] or d.get("errors"))
if actual and os.environ.get("PUBLISH")=="1":
    r=requests.put(f"https://{DOM}/admin/api/{V}/themes/{actual[0]['id']}.json",headers=H,json={"theme":{"id":actual[0]["id"],"role":"main"}})
    print("publish Actual:", r.status_code, r.text[:200])
print("products:", requests.get(f"https://{DOM}/admin/api/{V}/products/count.json",headers=H).text)
