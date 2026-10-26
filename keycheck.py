import os, requests
k=os.environ.get("DROPSHIP_API_KEY",""); s=os.environ.get("DROPSHIP_SECRET_KEY","")
print("api-key length:",len(k),"| starts/ends with space:",k!=k.strip(),"| secret length:",len(s),"| spaces:",s!=s.strip())
for label,h in [("as saved",{"api-key":k,"secret-key":s}),("trimmed",{"api-key":k.strip(),"secret-key":s.strip()}),("swapped",{"api-key":s.strip(),"secret-key":k.strip()})]:
    r=requests.get("https://mohasagor.com.bd/api/reseller/product?page=1",headers=h,timeout=30)
    print(label, r.status_code, r.text[:120] if not r.ok else ("total=%s"%r.json().get("total")))
