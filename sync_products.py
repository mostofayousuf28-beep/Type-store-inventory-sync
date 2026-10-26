"""
Supplier (mohasagor / dropshipping.com.bd) -> Shopify (nogoressetials.com) product sync.

Rules
-----
* Supplier products with the SAME NAME (usually the same item in another colour/design) become ONE Shopify
  product with a "Design" option (Design 1, Design 2, ...), each design showing its own picture.
  Products are matched only by supplier product_code (Shopify SKU = "<code>" or "<code>-<size>").
* Title on Shopify = "<supplier name> - <product_code of the first design>".
* Selling price = max(supplier retail price, dropshipper cost x MIN_MARKUP), rounded up to the next 10.
  (supplier "price" = Customer/Retail price, supplier "sale_price" = Dropshipper price / our cost)
* Compare-at ("crossed out") price: a discount between 15% and 35% that differs per product (not the same
  % everywhere), rounded up to the next 10.
* Descriptions: the supplier API strips all line breaks, so paragraphs, "Label: value" lines and bullet
  points are rebuilt, emojis removed, and the supplier's YouTube video (if any) is embedded.
* Every run brings title, description, category, images, variants and prices in line with the supplier;
  only products that actually changed are written.
* Tags: the category, plus "new-arrival" on the newest products (used by the New Arrivals collection).
  Other tags you add yourself (e.g. "best-seller") are kept.
* Supplier no longer lists a product -> DRAFT (never deleted); it comes back -> ACTIVE again.
  Old single products that were merged into a combined product -> DRAFT with tag "merged".
* A product tag like "price-1650" fixes that product's selling price; the sync keeps it instead of the formula.
* Only products with vendor "Supplier" are touched.
* If the supplier API cannot be read completely, nothing is changed and the run is marked failed.

Set DRY_RUN=1 to only print what would change.
"""

import hashlib
import html
import json
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

# ---------------------------------------------------------------- settings
MIN_MARKUP = float(os.environ.get("MIN_MARKUP", "1.70"))
DISCOUNTS = [0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.33, 0.35]
NEW_ARRIVALS_COUNT = 24
MAX_VARIANTS = 100            # Shopify REST limit per product
IMAGES_PER_DESIGN = 3         # pictures per design in a combined product
DRY_RUN = os.environ.get("DRY_RUN", "").strip() not in ("", "0", "false", "False")
VENDOR = "Supplier"
API_VERSION = "2026-04"
SUPPLIER_URL = "https://mohasagor.com.bd/api/reseller/product"
MAX_WRITE_FAILURES = 40
WORKERS = int(os.environ.get("CREATE_WORKERS", "6"))
NEW_TAG, MERGED_TAG = "new-arrival", "merged"

DROPSHIP_API_KEY = os.environ.get("DROPSHIP_API_KEY")
DROPSHIP_SECRET_KEY = os.environ.get("DROPSHIP_SECRET_KEY")
SHOPIFY_STORE_DOMAIN = os.environ.get("SHOPIFY_STORE_DOMAIN")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET")

HASH_NS, HASH_KEY = "sync", "hash"


class SyncAbort(Exception):
    pass


# ---------------------------------------------------------------- text helpers
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0000FE0F\U0000200D\U000E0020-\U000E007F"
    "←-⇿⌀-⏿■-◿✀-➿]")


def strip_emoji(s):
    s = re.sub(r"(\d)️?⃣", r"\n\1. ", s)          # keycap numbers 1️⃣ -> "1. "
    return EMOJI_RE.sub("\n", s)


def clean_name(s):
    s = strip_emoji(html.unescape(s or "")).replace("\n", " ")
    return " ".join(s.split()) or "Untitled Product"


LABEL = r"[A-Za-zঀ-৿][\wঀ-৿ '&/().%+-]{0,38}"


def format_description(raw, video_url=None):
    """Rebuild paragraphs / label lines / bullets that the supplier API flattened into one line."""
    t = html.unescape(raw or "").replace("\xa0", " ")
    t = re.sub(r"<[^>]+>", "\n", t)
    t = strip_emoji(t)
    t = re.sub(r"[ \t]+", " ", t)
    BN = "\u0980-\u09E5\u09F0-\u09FF"      # Bangla letters (without Bangla digits)
    # sentence ends glued to the next sentence: "।আধুনিক", "use.Beautifully"
    t = re.sub(r"([।!?])\s*(?=\S)", r"\1\n", t)
    t = re.sub(rf"(?<=[a-z{BN})\"”])\.(?=[A-Z{BN}])", ".\n", t)
    # numbered items glued to text: "safe to use.2. Beautifully" (but not decimals like 3.2V)
    t = re.sub(rf"(?<![\d\s,])(?<!\d\.)\s*(?=\b\d{{1,2}}[.)]\s?[A-Za-z{BN}])", "\n", t)
    # "Label:" glued to previous text: "silverSizes:", "(ঐচ্ছিক)উপাদান:", "ABSআলো জ্বলার সময়:", "Specifications:Fabric:"
    t = re.sub(r"(?<=[a-z0-9)\]\"”':])(?=[A-Z][\w '&/()-]{0,30}:)", "\n", t)
    t = re.sub(rf"(?<=[A-Za-z0-9)\]\"”:])(?=[{BN}][{BN} '&/()-]{{0,30}}:)", "\n", t)
    # bullets: ":-" / "--" / "- " at the start of a line
    t = re.sub(r":\s*-+\s*", ":\n- ", t)
    t = re.sub(r"(?<=[।!?.:])\s*-+\s+(?=\S)", "\n- ", t)

    lines = [l.strip(" -–•*") for l in t.split("\n")]
    lines = [l for l in (x.strip() for x in lines) if l]
    out, ul = [], []

    def flush():
        if ul:
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in ul) + "</ul>")
            ul.clear()

    for line in lines:
        esc = html.escape(line, quote=False)
        m = re.match(rf"^({LABEL}):\s*(.*)$", line)
        num = re.match(r"^\d{1,2}[.)]\s*([^\d\s].*)$", line)
        if m and m.group(2):
            ul.append(f"<strong>{html.escape(m.group(1), quote=False)}:</strong> {html.escape(m.group(2), quote=False)}")
        elif num:
            ul.append(html.escape(num.group(1), quote=False))
        elif m and not m.group(2):                       # heading line "Specifications:"
            flush(); out.append(f"<h4>{esc}</h4>")
        else:
            flush(); out.append(f"<p>{esc}</p>")
    flush()
    body = "\n".join(out)
    if video_url and re.match(r"^https://www\.youtube\.com/embed/[\w-]{6,20}$", video_url.strip()):
        body += ('\n<div style="position:relative;padding-top:56.25%;margin-top:18px;border-radius:12px;overflow:hidden">'
                 f'<iframe src="{video_url.strip()}" title="Product video" loading="lazy" allowfullscreen '
                 'style="position:absolute;inset:0;width:100%;height:100%;border:0"></iframe></div>')
    return body


def norm(s):
    return " ".join(clean_name(s).lower().split())


# ---------------------------------------------------------------- price helpers
def round_up_10(x):
    return int(math.ceil(float(x) / 10.0) * 10)


def sell_price(item):
    retail = float(item.get("price") or 0)
    cost = float(item.get("sale_price") or 0)
    if cost <= 0 and retail <= 0:
        return None
    return round_up_10(max(retail, cost * MIN_MARKUP if cost > 0 else 0))


def compare_at(sell, code):
    d = DISCOUNTS[int(hashlib.md5(str(code).encode()).hexdigest(), 16) % len(DISCOUNTS)]
    return round_up_10(sell / (1 - d))


def short_hash(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def encode_hash(h, drafted_by_sync=False):
    s = f"c:{h.get('c')}|i:{h.get('i')}|v:{h.get('v')}"
    return s + "|d:1" if drafted_by_sync else s


def decode_hash(s):
    out = {}
    for part in (s or "").split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k] = v
    return out


def code_of(item):
    return str(item.get("product_code") or "").strip()


def image_urls(item):
    urls = []
    thumb = item.get("thumbnail_img") or ""
    if thumb.startswith("http"):
        urls.append(thumb)
    for img in item.get("product_images") or []:
        u = (img or {}).get("product_image") or ""
        if u.startswith("http") and u not in urls:
            urls.append(u)
    return urls


def size_list(item):
    out, seen = [], set()
    for v in item.get("product_variants") or []:
        val = " ".join(str(v.get("variant") or "").split())
        if val and val.lower() not in seen:
            seen.add(val.lower())
            out.append((str(v.get("attribute") or "Option").strip() or "Option", val))
    return out


def base_code(sku):
    return (sku or "").split("-")[0].strip()


# ---------------------------------------------------------------- desired state per group
def build_groups(supplier):
    """supplier: {code: item} -> list of member lists (same name), chunked to stay under the variant limit."""
    by_name = {}
    for c, it in supplier.items():
        if sell_price(it):
            by_name.setdefault(norm(it.get("name")), []).append(it)
    groups = []
    for members in by_name.values():
        members.sort(key=lambda x: int(code_of(x)) if code_of(x).isdigit() else 0)
        chunk, count = [], 0
        for m in members:
            n = max(1, len(size_list(m)))
            if chunk and count + n > MAX_VARIANTS:
                groups.append(chunk); chunk, count = [], 0
            chunk.append(m); count += n
        if chunk:
            groups.append(chunk)
    return groups


def desired_group(members, new_codes):
    first = members[0]
    pcode = code_of(first)
    multi = len(members) > 1
    attr = next((size_list(m)[0][0] for m in members if size_list(m)), None)
    options = (["Design"] if multi else []) + ([attr] if attr else [])

    variants, images, first_img = [], [], {}
    for i, m in enumerate(members, 1):
        code = code_of(m)
        sp = sell_price(m)
        ca = compare_at(sp, pcode)
        sizes = size_list(m)
        label = f"Design {i}"
        if sizes:
            for _, val in sizes:
                opts = ([label] if multi else []) + [val]
                variants.append({"opts": opts, "sku": f"{code}-{val}", "price": sp, "compare_at": ca, "code": code})
        else:
            opts = ([label] if multi else []) + (["Standard"] if attr else [])
            variants.append({"opts": opts, "sku": code, "price": sp, "compare_at": ca, "code": code})
        urls = image_urls(m)[: (IMAGES_PER_DESIGN if multi else 50)]
        for u in urls:
            if u not in images:
                images.append(u)
        if urls:
            first_img[code] = images.index(urls[0])

    category = str(first.get("category") or "").strip() or "Uncategorized"
    title = f"{clean_name(first.get('name'))} - {pcode}"
    video = next((m.get("video_url") for m in members if m.get("video_url")), None)
    body = format_description(first.get("details"), video)
    tags = {category} | ({NEW_TAG} if any(code_of(m) in new_codes for m in members) else set())
    return {
        "codes": [code_of(m) for m in members], "multi": multi, "title": title, "body_html": body,
        "category": category, "options": options, "variants": variants, "images": images,
        "first_img": first_img, "tags": tags,
        "hash": {"c": short_hash([title, body, category]), "i": short_hash(images),
                 "v": short_hash([[v["sku"], v["opts"]] for v in variants])},
    }


# ---------------------------------------------------------------- supplier
def fetch_supplier_products():
    headers = {"api-key": DROPSHIP_API_KEY, "secret-key": DROPSHIP_SECRET_KEY}
    items, page, last_page, expected_total = [], 1, None, None
    while True:
        data = None
        for attempt in range(1, 5):
            try:
                r = requests.get(f"{SUPPLIER_URL}?page={page}", headers=headers, timeout=30)
                if r.status_code == 200:
                    data = r.json(); break
                print(f"Supplier page {page}: HTTP {r.status_code} (attempt {attempt}/4) {r.text[:150]}")
            except Exception as e:
                print(f"Supplier page {page}: network error (attempt {attempt}/4): {e}")
            time.sleep(5 * attempt)
        if data is None:
            raise SyncAbort(f"Supplier API failed on page {page} after 4 attempts. Nothing was changed on Shopify.")
        products = data.get("products")
        if isinstance(products, dict):
            products = products.get("data") or []
        items.extend(products or [])
        last_page = int(data.get("last_page") or 1)
        expected_total = expected_total or data.get("total")
        if page >= last_page:
            break
        page += 1
        time.sleep(0.3)
    if expected_total and len(items) < int(expected_total):
        raise SyncAbort(f"Supplier returned {len(items)} products but said total={expected_total}. Nothing was changed.")
    if not items:
        raise SyncAbort("Supplier returned 0 products. Nothing was changed.")
    by_code = {code_of(it): it for it in items if code_of(it)}
    print(f"Supplier: {len(items)} products on {last_page} pages ({len(by_code)} unique codes)")
    return by_code


# ---------------------------------------------------------------- shopify
class Shopify:
    def __init__(self):
        self.base = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}"
        self.token = self._token()
        self.write_failures = 0
        self._lock = threading.Lock()

    def _token(self):
        r = requests.post(f"https://{SHOPIFY_STORE_DOMAIN}/admin/oauth/access_token",
                          data={"grant_type": "client_credentials", "client_id": SHOPIFY_CLIENT_ID,
                                "client_secret": SHOPIFY_CLIENT_SECRET}, timeout=20)
        tok = r.json().get("access_token") if r.ok else None
        if not tok:
            raise SyncAbort(f"Could not log in to Shopify (HTTP {r.status_code}): {r.text[:200]}")
        return tok

    def _req(self, method, path, **kw):
        url = path if path.startswith("http") else self.base + path
        headers = {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}
        for attempt in range(1, 6):
            try:
                r = requests.request(method, url, headers=headers, timeout=90, **kw)
            except Exception as e:
                print(f"  network error {method} {path} (attempt {attempt}/5): {e}")
                if method == "POST":
                    return None          # never resend a create: it may have gone through
                time.sleep(3 * attempt); continue
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2))); continue
            if r.status_code >= 500 and method != "POST":
                time.sleep(3 * attempt); continue
            used = r.headers.get("X-Shopify-Shop-Api-Call-Limit", "0/40").split("/")
            if len(used) == 2 and int(used[0]) > int(used[1]) - 8:
                time.sleep(1.5)
            return r
        return None

    def graphql(self, query, variables=None):
        for attempt in range(1, 8):
            r = self._req("POST", "/graphql.json", json={"query": query, "variables": variables or {}})
            if r is None or not r.ok:
                if attempt < 7:
                    time.sleep(3 * attempt); continue
                raise SyncAbort(f"Shopify GraphQL failed: {r.status_code if r else 'no response'}")
            body = r.json()
            errs = body.get("errors")
            if errs and "THROTTLED" in json.dumps(errs):
                time.sleep(2 * attempt); continue
            if errs:
                raise SyncAbort(f"Shopify GraphQL error: {errs}")
            cost = (body.get("extensions") or {}).get("cost", {}).get("throttleStatus", {})
            if cost and cost.get("currentlyAvailable", 1000) < 300:
                time.sleep(2)
            return body["data"]
        raise SyncAbort("Shopify GraphQL throttled too long")

    def load_catalog(self):
        q = """
        query($cursor: String) {
          products(first: 8, after: $cursor, query: "vendor:Supplier") {
            pageInfo { hasNextPage endCursor }
            nodes {
              legacyResourceId title status vendor productType createdAt tags
              featuredImage { id }
              metafield(namespace: "%s", key: "%s") { value }
              options { name }
              variants(first: 100) { nodes { legacyResourceId sku price compareAtPrice selectedOptions { value } } }
            }
          }
        }""" % (HASH_NS, HASH_KEY)
        products, cursor = [], None
        while True:
            data = self.graphql(q, {"cursor": cursor})["products"]
            for n in data["nodes"]:
                if n["vendor"] != VENDOR:
                    continue
                opts = [o["name"] for o in (n["options"] or [])]
                if opts == ["Title"]:
                    opts = []
                products.append({
                    "id": int(n["legacyResourceId"]), "title": n["title"], "status": n["status"],
                    "product_type": n["productType"] or "", "created_at": n["createdAt"], "tags": set(n["tags"] or []),
                    "has_image": bool(n["featuredImage"]),
                    "hash": decode_hash((n["metafield"] or {}).get("value")), "options": opts,
                    "variants": [{"id": int(v["legacyResourceId"]), "sku": v["sku"] or "",
                                  "price": float(v["price"] or 0), "compare_at": float(v["compareAtPrice"] or 0),
                                  "opts": [o["value"] for o in v["selectedOptions"]] if opts else []}
                                 for v in n["variants"]["nodes"]],
                })
            if not data["pageInfo"]["hasNextPage"]:
                break
            cursor = data["pageInfo"]["endCursor"]
        print(f"Shopify: {len(products)} supplier products in store")
        return products

    def _ok(self, r, what):
        if r is not None and r.status_code in (200, 201):
            return r
        with self._lock:
            self.write_failures += 1
        print(f"  x {what}: {r.status_code if r is not None else 'no response'} {r.text[:300] if r is not None else ''}")
        return None

    @staticmethod
    def variant_payload(D, existing=None):
        existing = existing or {}
        out = []
        for v in D["variants"]:
            pv = {"price": str(v["price"]), "compare_at_price": str(v["compare_at"]), "sku": v["sku"],
                  "inventory_management": None}
            for i, o in enumerate(v["opts"][:3], 1):
                pv[f"option{i}"] = o
            if v["sku"] in existing:
                pv["id"] = existing[v["sku"]]
            out.append(pv)
        return out

    def link_variant_images(self, pid, D, product_json=None):
        if not D["multi"]:
            return
        if product_json is None:
            r = self._req("GET", f"/products/{pid}.json?fields=images,variants")
            if r is None or not r.ok:
                return
            product_json = r.json()["product"]
        imgs = sorted(product_json.get("images") or [], key=lambda x: x["position"])
        for code, idx in D["first_img"].items():
            if idx >= len(imgs):
                continue
            vids = [v["id"] for v in product_json.get("variants") or [] if base_code(v.get("sku")) == code]
            if vids:
                self._req("PUT", f"/products/{pid}/images/{imgs[idx]['id']}.json",
                          json={"image": {"id": imgs[idx]["id"], "variant_ids": vids}})

    def create_product(self, D):
        many = len(D["images"]) > 8
        payload = {"product": {
            "title": D["title"], "body_html": D["body_html"], "vendor": VENDOR,
            "product_type": D["category"], "tags": ", ".join(sorted(D["tags"])), "status": "active",
            "variants": Shopify.variant_payload(D),
            "metafields": [{"namespace": HASH_NS, "key": HASH_KEY, "type": "single_line_text_field",
                            "value": encode_hash(D["hash"])}],
        }}
        if not many:
            payload["product"]["images"] = [{"src": u} for u in D["images"]]
        if D["options"]:
            payload["product"]["options"] = [{"name": o} for o in D["options"]]
        r = self._ok(self._req("POST", "/products.json", json=payload), f"create {D['title']}")
        if not r:
            return None
        prod = r.json()["product"]
        if many:
            # big combined products: add pictures one by one (one request with 50+ pictures times out)
            vids_by_code = {}
            for v in prod.get("variants") or []:
                vids_by_code.setdefault(base_code(v.get("sku")), []).append(v["id"])
            first_of = {idx: code for code, idx in D["first_img"].items()}
            for idx, url in enumerate(D["images"]):
                img = {"src": url, "position": idx + 1}
                if idx in first_of:
                    img["variant_ids"] = vids_by_code.get(first_of[idx], [])
                rr = self._req("POST", f"/products/{prod['id']}/images.json", json={"image": img})
                if rr is None or rr.status_code not in (200, 201):
                    print(f"  ! picture {idx + 1} for {D['title']}: {rr.status_code if rr is not None else 'no response'}")
        else:
            self.link_variant_images(prod["id"], D, prod)
        return prod["id"]

    def update_product(self, pid, payload, what):
        payload["id"] = pid
        r = self._ok(self._req("PUT", f"/products/{pid}.json", json={"product": payload}), what)
        return r.json()["product"] if r else None

    def update_variant(self, vid, price, compare_at, what):
        payload = {"variant": {"id": vid, "price": str(price), "compare_at_price": str(compare_at)}}
        return self._ok(self._req("PUT", f"/variants/{vid}.json", json=payload), what) is not None

    def set_hashes(self, pairs):
        m = """mutation($m: [MetafieldsSetInput!]!) { metafieldsSet(metafields: $m) { userErrors { field message } } }"""
        for i in range(0, len(pairs), 25):
            inp = [{"ownerId": f"gid://shopify/Product/{pid}", "namespace": HASH_NS, "key": HASH_KEY,
                    "type": "single_line_text_field", "value": h} for pid, h in pairs[i:i + 25]]
            try:
                errs = self.graphql(m, {"m": inp})["metafieldsSet"]["userErrors"]
                if errs:
                    print(f"  x saving sync markers: {errs[:3]}"); self.write_failures += 1
            except SyncAbort as e:
                print(f"  x saving sync markers: {e}"); self.write_failures += 1


# ---------------------------------------------------------------- planning
MANAGED_TAGS = {NEW_TAG}


PRICE_TAG = re.compile(r"^price-(\d{2,6})$")


def apply_price_override(p, D):
    """A tag like "price-1650" on a Shopify product fixes its selling price (compare-at follows automatically)."""
    fixed = next((int(m.group(1)) for t in p["tags"] for m in [PRICE_TAG.match(t.strip().lower())] if m), None)
    if not fixed:
        return D
    D = dict(D)
    ca = compare_at(fixed, D["codes"][0])
    D["variants"] = [dict(v, price=fixed, compare_at=ca) for v in D["variants"]]
    return D


def plan_update(p, D, all_categories):
    D = apply_price_override(p, D)
    reasons, payload, var_updates = [], {}, []
    old_h = p["hash"]
    first_sync = not old_h

    if p["title"] != D["title"]:
        payload["title"] = D["title"]; reasons.append("title")
    if p["product_type"] != D["category"]:
        payload["product_type"] = D["category"]; reasons.append("category")
    if first_sync or old_h.get("c") != D["hash"]["c"]:
        payload["body_html"] = D["body_html"]; reasons.append("details")
    if p["status"] != "ACTIVE" and old_h.get("d") == "1":
        payload["status"] = "active"; reasons.append("re-activate")

    keep = {t for t in p["tags"] if t not in MANAGED_TAGS and t not in all_categories}
    want_tags = keep | D["tags"]
    if want_tags != p["tags"]:
        payload["tags"] = ", ".join(sorted(want_tags)); reasons.append("tags")

    images_changed = (first_sync and not p["has_image"] and D["images"]) or \
                     (not first_sync and old_h.get("i") != D["hash"]["i"])
    if images_changed:
        payload["images"] = [{"src": u} for u in D["images"]]; reasons.append("images")

    have = {v["sku"]: v for v in p["variants"]}
    same_structure = set(have) == {v["sku"] for v in D["variants"]} and \
        all(have[v["sku"]]["opts"] == v["opts"] for v in D["variants"])
    if not same_structure:
        payload["options"] = [{"name": o} for o in D["options"]] if D["options"] else [{"name": "Title"}]
        payload["variants"] = Shopify.variant_payload(D, {s: v["id"] for s, v in have.items()})
        reasons.append("variants")
    else:
        for v in D["variants"]:
            ex = have[v["sku"]]
            if abs(ex["price"] - v["price"]) > 0.01 or abs(ex["compare_at"] - v["compare_at"]) > 0.01:
                var_updates.append((ex["id"], v["price"], v["compare_at"]))
        if var_updates:
            reasons.append("price")

    new_hash = encode_hash(D["hash"])
    stored = encode_hash(old_h, drafted_by_sync=old_h.get("d") == "1")
    if old_h.get("d") == "1" and "status" not in payload:
        new_hash = stored
    hash_str = new_hash if new_hash != stored else None
    return (payload or None), var_updates, hash_str, reasons, images_changed or not same_structure


# ---------------------------------------------------------------- main
def main():
    print(f"Mode: {'DRY RUN (no changes)' if DRY_RUN else 'LIVE'} | min markup x{MIN_MARKUP} | varied compare-at")
    supplier = fetch_supplier_products()
    shop = Shopify()
    catalog = shop.load_catalog()
    all_categories = {str(it.get("category") or "").strip() or "Uncategorized" for it in supplier.values()}

    groups = build_groups(supplier)
    newest = sorted(groups, key=lambda g: max(int(code_of(m)) if code_of(m).isdigit() else 0 for m in g), reverse=True)
    new_codes = {code_of(m) for g in newest[:NEW_ARRIVALS_COUNT] for m in g}
    print(f"Groups: {len(groups)} products to show ({sum(1 for g in groups if len(g) > 1)} combined from same-name items)")

    prods_by_code = {}
    for p in catalog:
        p["codes"] = {base_code(v["sku"]) for v in p["variants"] if v["sku"]} - {""}
        for c in p["codes"]:
            prods_by_code.setdefault(c, []).append(p)

    stats = {k: 0 for k in ("created", "updated", "price_only", "unchanged", "drafted_gone",
                            "drafted_merged", "drafted_duplicate")}
    reasons_count, samples, hashes, to_create, to_update, to_draft = {}, [], [], [], [], {}
    claimed = set()

    def log(s):
        if len(samples) < 50:
            samples.append(s)

    for members in groups:
        D = desired_group(members, new_codes)
        cands = {}
        for c in D["codes"]:
            for p in prods_by_code.get(c, []):
                cands[p["id"]] = p
        cands = list(cands.values())
        # keeper: a product with exactly the same option layout (a previously combined product, or the single)
        keeper = None
        for p in sorted(cands, key=lambda x: (-len(x["codes"] & set(D["codes"])), x["created_at"])):
            if p["id"] in claimed:
                continue
            if p["options"] == D["options"] or (not D["multi"] and len(p["codes"]) == 1):
                keeper = p; break
        for p in cands:
            if p is keeper or p["id"] in claimed:
                continue
            claimed.add(p["id"])
            if p["status"] == "ACTIVE":
                kind = "drafted_merged" if D["multi"] else "drafted_duplicate"
                to_draft[p["id"]] = (p, kind)
        if keeper is None:
            to_create.append(D); stats["created"] += 1
            log(f"+ new{' (combined ' + str(len(members)) + ' designs)' if D['multi'] else ''}: {D['title']}")
            continue
        claimed.add(keeper["id"])
        payload, var_updates, h, reasons, relink = plan_update(keeper, D, all_categories)
        for r in reasons:
            reasons_count[r] = reasons_count.get(r, 0) + 1
        if not payload and not var_updates:
            stats["unchanged"] += 1
        else:
            stats["updated" if payload else "price_only"] += 1
            log(f"~ {D['title']} [{', '.join(reasons)}]")
            to_update.append((keeper, D, payload, var_updates, relink))
        if h:
            hashes.append((keeper["id"], h))

    # products whose supplier codes are all gone
    live_codes = set(supplier)
    for p in catalog:
        if p["id"] in claimed or not p["codes"]:
            continue
        if not (p["codes"] & live_codes) and p["status"] == "ACTIVE":
            to_draft[p["id"]] = (p, "drafted_gone")

    for pid, (p, kind) in to_draft.items():
        stats[kind] += 1
        log(f"- {kind.replace('_', ' ')}: {p['title']}")

    print("\n--- sample of changes ---")
    for s in samples:
        print(s)
    print("\n--- summary ---")
    for k, v in stats.items():
        print(f"{k:>18}: {v}")
    print(f"{'change reasons':>18}: {reasons_count}")
    if DRY_RUN:
        ex = next((D for D in (desired_group(g, new_codes) for g in groups) if D["multi"]), None)
        if ex:
            print("\n--- example combined product ---")
            print(ex["title"], ex["options"], [(v["sku"], v["opts"], v["price"], v["compare_at"]) for v in ex["variants"]][:8])
        sample = desired_group(groups[len(groups) // 3], new_codes)
        print("\n--- example description ---\n", sample["body_html"][:1500])
        return

    # ---- writes
    def _draft(item):
        pid, (p, kind) = item
        tags = set(p["tags"]) | ({MERGED_TAG} if kind == "drafted_merged" else set())
        if shop.update_product(pid, {"status": "draft", "tags": ", ".join(sorted(tags))}, f"draft {p['title']}"):
            if kind == "drafted_gone":
                with shop._lock:
                    hashes.append((pid, encode_hash(p["hash"], drafted_by_sync=True)))

    def _update(job):
        p, D, payload, var_updates, relink = job
        if payload:
            if var_updates and "variants" not in payload:
                payload["variants"] = [{"id": vid, "price": str(pr), "compare_at_price": str(ca)}
                                       for vid, pr, ca in var_updates]
            prod = shop.update_product(p["id"], payload, f"update {D['title']}")
            if prod and relink:
                shop.link_variant_images(p["id"], D)
        else:
            for vid, pr, ca in var_updates:
                shop.update_variant(vid, pr, ca, f"price {D['title']}")

    for label, fn, jobs in (("Creating", shop.create_product, to_create),
                            ("Updating", _update, to_update),
                            ("Hiding", _draft, list(to_draft.items()))):
        if not jobs:
            continue
        print(f"{label} {len(jobs)} products ...")
        done = [0]

        def run(job, fn=fn, total=len(jobs), label=label):
            fn(job)
            with shop._lock:
                done[0] += 1
                if done[0] % 200 == 0:
                    print(f"  ... {label.lower()} {done[0]}/{total}")
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(run, jobs))

    if hashes:
        shop.set_hashes(hashes)
    print(f"{'write failures':>18}: {shop.write_failures}")
    if shop.write_failures > MAX_WRITE_FAILURES:
        raise SyncAbort(f"{shop.write_failures} Shopify writes failed (limit {MAX_WRITE_FAILURES}).")


if __name__ == "__main__":
    try:
        main()
    except SyncAbort as e:
        print(f"\nSYNC STOPPED: {e}")
        sys.exit(1)
