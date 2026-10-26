import os, requests, time
k=os.environ.get("DROPSHIP_API_KEY",""); s=os.environ.get("DROPSHIP_SECRET_KEY","")
shown="2ff380917a11d3a7c97bcf6dddfb8adf38194c7d6b726ab12c4"
print("key matches panel:", k=="A8niclztH9JtzS4t", "| secret starts like panel:", s.startswith(shown), "| secret len:", len(s))
for i in range(3):
    r=requests.get("https://mohasagor.com.bd/api/reseller/product?page=1",headers={"api-key":k,"secret-key":s,"Accept":"application/json","User-Agent":"Mozilla/5.0"},timeout=30)
    print(r.status_code, r.headers.get("server"), r.text[:150]); time.sleep(3)
