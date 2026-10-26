import os, requests
k=os.environ.get("DROPSHIP_API_KEY",""); s=os.environ.get("DROPSHIP_SECRET_KEY","")
print("api-key length:",len(k),"| starts/ends with space:",k!=k.strip(),"| secret length:",len(s),"| spaces:",s!=s.strip())
for label,h in [("as saved",{"api-key":k,"secret-key":s}),("trimmed",{"api-key":k.strip(),"secret-key":s.strip()}),("swapped",{"api-key":s.strip(),"secret-key":k.strip()})]:
    r=requests.get("https://mohasagor.com.bd/api/reseller/product?page=1",headers=h,timeout=30)
    print(label, r.status_code, r.text[:120] if not r.ok else ("total=%s"%r.json().get("total")))

import hashlib
print("api-key fingerprint:", hashlib.sha256(k.encode()).hexdigest()[:10], "| secret fingerprint:", hashlib.sha256(s.encode()).hexdigest()[:10])
for url in ["https://mohasagor.com.bd/api/reseller/product","https://dropshipping.com.bd/api/reseller/product"]:
    r=requests.get(url+"?page=1",headers={"api-key":k,"secret-key":s},timeout=30)
    print(url, r.status_code, r.text[:100] if not r.ok else "OK total=%s"%r.json().get("total"))
# run 1793040145
