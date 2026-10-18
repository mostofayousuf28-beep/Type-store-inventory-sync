"""
Supplier (mohasagor / dropshipping.com.bd) -> Shopify (nogoressentials.com) product sync.

Rules
-----
* A product is identified ONLY by the supplier product_code (Shopify SKU = "<code>" or "<code>-<variant>").
  Titles are never used for matching, so two different products with the same name are both kept.
* Title on Shopify = "<supplier name> - <product_code>".
* Selling price  = max(supplier retail price, dropshipper cost x MIN_MARKUP), rounded UP to the next 10.
  (supplier "price" = Customer/Retail price, supplier "sale_price" = Dropshipper price / our cost)
* Compare-at ("crossed out") price = selling price x (1 + COMPARE_AT_PCT), rounded UP to the next 10.
* Every run: price, compare-at, title, details, category, images and variants are brought in line with the supplier.
  Only products that actually changed are written.
* Supplier no longer lists a product  -> Shopify product is set to DRAFT (hidden, never deleted).
  Supplier lists it again               -> set back to ACTIVE.
* Only products with vendor "Supplier" are touched; anything added by hand on Shopify is left alone.
* If the supplier API cannot be read completely, the run stops BEFORE changing anything and the
  GitHub Action is marked as failed (GitHub then emails you).

Set DRY_RUN=1 to only print what would change.
"""

import hashlib
import json
import math
import os
import sys
import time

import requests

# ---------------------------------------------------------------- settings
MIN_MARKUP = float(os.environ.get("MIN_MARKUP", "1.70"))          # at least 70% profit on cost
COMPARE_AT_PCT = float(os.environ.get("COMPARE_AT_PCT", "0.30"))  # crossed-out price 30% above selling price
DRY_RUN = os.environ.get("DRY_RUN", "").strip() not in ("", "0", "false", "False")
VENDOR = "Supplier"
API_VERSION = "2026-04"
SUPPLIER_URL = "https://mohasagor.com.bd/api/reseller/product"
MAX_WRITE_FAILURES = 25   # more failed Shopify writes than this -> mark the run as failed

DROPSHIP_API_KEY = os.environ.get("DROPSHIP_API_KEY")
DROPSHIP_SECRET_KEY = os.environ.get("DROPSHIP_SECRET_KEY")
SHOPIFY_STORE_DOMAIN = os.environ.get("SHOPIFY_STORE_DOMAIN")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET")

HASH_NS, HASH_KEY = "sync", "hash"


class SyncAbort(Exception):
    pass


# ---------------------------------------------------------------- helpers
def round_up_10(x):
    return int(math.ceil(float(x) / 10.0) * 10)


def compute_prices(item):
    retail = float(item.get("price") or 0)
    cost = float(item.get("sale_price") or 0)
    if cost <= 0 and retail <= 0:
        return None, None
    floor_price = cost * MIN_MARKUP if cost > 0 else 0
    sell = round_up_10(max(retail, floor_price))
    compare_at = round_up_10(sell * (1 + COMPARE_AT_PCT))
    return sell, compare_at


def short_hash(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def code_of(item):
    return str(item.get("product_code") or "").strip()


def build_title(item):
    name = " ".join(str(item.get("name") or "Untitled Product").split())
    return f"{name} - {code_of(item)}"


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


def variant_list(item):
    """[(option_name, value)] in supplier order, de-duplicated."""
    out, seen = [], set()
    for v in item.get("product_variants") or []:
        val = " ".join(str(v.get("variant") or "").split())
        if val and val.lower() not in seen:
            seen.add(val.lower())
            out.append((str(v.get("attribute") or "Option").strip() or "Option", val))
    return out


def sku_for(code, value=None):
    return f"{code}-{value}" if value else code


def desired_state(item):
    code = code_of(item)
    sell, compare_at = compute_prices(item)
    variants = variant_list(item)
    category = str(item.get("category") or "").strip() or "Uncategorized"
    content = {"t": build_title(item), "d": item.get("details") or "", "c": category}
    imgs = image_urls(item)
    return {
        "code": code,
        "title": content["t"],
        "body_html": content["d"],
        "category": category,
        "price": sell,
        "compare_at": compare_at,
        "variants": variants,
        "option_name": variants[0][0] if variants else None,
        "images": imgs,
        "hash": {
            "c": short_hash(content),
            "i": short_hash(imgs),
            "v": short_hash([v for _, v in variants]),
        },
    }


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
                    data = r.json()
                    break
                print(f"Supplier page {page}: HTTP {r.status_code} (attempt {attempt}/4) {r.text[:150]}")
            except Exception as e:
                print(f"Supplier page {page}: network error (attempt {attempt}/4): {e}")
            time.sleep(5 * attempt)
        if data is None:
            raise SyncAbort(f"Supplier API failed on page {page} after 4 attempts. Nothing was changed on Shopify.")

        products = data.get("products")
        if isinstance(products, dict):
            last_page = last_page or products.get("last_page")
            products = products.get("data") or []
        items.extend(products or [])
        last_page = int(data.get("last_page") or last_page or 1)
        expected_total = expected_total or data.get("total")
        if page >= last_page:
            break
        page += 1
        time.sleep(0.3)

    if expected_total and len(items) < int(expected_total):
        raise SyncAbort(f"Supplier returned {len(items)} products but said total={expected_total}. Nothing was changed.")
    if not items:
        raise SyncAbort("Supplier returned 0 products. Nothing was changed.")

    by_code = {}
    for it in items:
        c = code_of(it)
        if c:
            by_code[c] = it
    print(f"Supplier: {len(items)} products on {last_page} pages ({len(by_code)} unique codes)")
    return by_code


# ---------------------------------------------------------------- shopify
class Shopify:
    def __init__(self):
        self.base = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{API_VERSION}"
        self.token = self._token()
        self.write_failures = 0

    def _token(self):
        r = requests.post(
            f"https://{SHOPIFY_STORE_DOMAIN}/admin/oauth/access_token",
            data={"grant_type": "client_credentials", "client_id": SHOPIFY_CLIENT_ID, "client_secret": SHOPIFY_CLIENT_SECRET},
            timeout=20,
        )
        tok = r.json().get("access_token") if r.ok else None
        if not tok:
            raise SyncAbort(f"Could not log in to Shopify (HTTP {r.status_code}): {r.text[:200]}")
        return tok

    def _req(self, method, path, **kw):
        url = path if path.startswith("http") else self.base + path
        headers = {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}
        for attempt in range(1, 6):
            try:
                r = requests.request(method, url, headers=headers, timeout=40, **kw)
            except Exception as e:
                print(f"  network error {method} {path} (attempt {attempt}/5): {e}")
                time.sleep(3 * attempt)
                continue
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            if r.status_code >= 500:
                time.sleep(3 * attempt)
                continue
            # stay under the REST leaky bucket
            used = r.headers.get("X-Shopify-Shop-Api-Call-Limit", "0/40").split("/")
            if len(used) == 2 and int(used[0]) > int(used[1]) - 8:
                time.sleep(1.5)
            return r
        return None

    def graphql(self, query, variables=None):
        for attempt in range(1, 6):
            r = self._req("POST", "/graphql.json", json={"query": query, "variables": variables or {}})
            if r is None or not r.ok:
                raise SyncAbort(f"Shopify GraphQL failed: {r.status_code if r else 'no response'} {r.text[:200] if r else ''}")
            body = r.json()
            errs = body.get("errors")
            if errs and any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errs):
                time.sleep(2 * attempt)
                continue
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
          products(first: 15, after: $cursor, query: "vendor:Supplier") {
            pageInfo { hasNextPage endCursor }
            nodes {
              legacyResourceId title status vendor productType createdAt
              featuredImage { id }
              metafield(namespace: "%s", key: "%s") { value }
              options { name }
              variants(first: 50) { nodes { legacyResourceId sku price compareAtPrice } }
            }
          }
        }""" % (HASH_NS, HASH_KEY)
        products, cursor = [], None
        while True:
            data = self.graphql(q, {"cursor": cursor})["products"]
            for n in data["nodes"]:
                if n["vendor"] != VENDOR:
                    continue
                products.append({
                    "id": int(n["legacyResourceId"]),
                    "title": n["title"],
                    "status": n["status"],
                    "product_type": n["productType"] or "",
                    "created_at": n["createdAt"],
                    "has_image": bool(n["featuredImage"]),
                    "hash": decode_hash((n["metafield"] or {}).get("value")),
                    "option_name": (n["options"] or [{}])[0].get("name"),
                    "variants": [
                        {"id": int(v["legacyResourceId"]), "sku": v["sku"] or "",
                         "price": float(v["price"] or 0), "compare_at": float(v["compareAtPrice"] or 0)}
                        for v in n["variants"]["nodes"]
                    ],
                })
            if not data["pageInfo"]["hasNextPage"]:
                break
            cursor = data["pageInfo"]["endCursor"]
        print(f"Shopify: {len(products)} supplier products in store")
        return products

    # ---- writes
    def _ok(self, r, what):
        if r is not None and r.status_code in (200, 201):
            return r
        self.write_failures += 1
        print(f"  ✗ {what}: {r.status_code if r is not None else 'no response'} {r.text[:300] if r is not None else ''}")
        return None

    def create_product(self, d):
        variants = []
        if d["variants"]:
            for _, val in d["variants"]:
                variants.append({"option1": val, "price": str(d["price"]), "compare_at_price": str(d["compare_at"]),
                                 "sku": sku_for(d["code"], val), "inventory_management": None})
        else:
            variants.append({"price": str(d["price"]), "compare_at_price": str(d["compare_at"]),
                             "sku": d["code"], "inventory_management": None})
        payload = {"product": {
            "title": d["title"], "body_html": d["body_html"], "vendor": VENDOR,
            "product_type": d["category"], "tags": d["category"], "status": "active",
            "images": [{"src": u} for u in d["images"]],
            "variants": variants,
            "metafields": [{"namespace": HASH_NS, "key": HASH_KEY, "type": "single_line_text_field",
                            "value": encode_hash(d["hash"])}],
        }}
        if d["variants"]:
            payload["product"]["options"] = [{"name": d["option_name"]}]
        r = self._ok(self._req("POST", "/products.json", json=payload), f"create {d['title']}")
        return r.json()["product"]["id"] if r else None

    def update_product(self, pid, payload, what):
        payload["id"] = pid
        return self._ok(self._req("PUT", f"/products/{pid}.json", json={"product": payload}), what) is not None

    def update_variant(self, vid, price, compare_at, what):
        payload = {"variant": {"id": vid, "price": str(price), "compare_at_price": str(compare_at)}}
        return self._ok(self._req("PUT", f"/variants/{vid}.json", json=payload), what) is not None

    def set_hashes(self, pairs):
        """pairs: [(product_id, hash_string)]"""
        m = """mutation($m: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $m) { userErrors { field message } } }"""
        for i in range(0, len(pairs), 25):
            chunk = pairs[i:i + 25]
            inp = [{"ownerId": f"gid://shopify/Product/{pid}", "namespace": HASH_NS, "key": HASH_KEY,
                    "type": "single_line_text_field", "value": h} for pid, h in chunk]
            try:
                errs = self.graphql(m, {"m": inp})["metafieldsSet"]["userErrors"]
                if errs:
                    print(f"  ✗ saving sync markers: {errs[:3]}")
                    self.write_failures += 1
            except SyncAbort as e:
                print(f"  ✗ saving sync markers: {e}")
                self.write_failures += 1


# ---------------------------------------------------------------- planning
def base_code(sku):
    return (sku or "").split("-")[0].strip()


def plan_update(p, d):
    """Return (product_payload or None, [variant price updates], new_hash_string or None, reasons)."""
    reasons, payload, var_updates = [], {}, []
    old_h = p["hash"]
    first_sync = not old_h

    if p["title"] != d["title"]:
        payload["title"] = d["title"]; reasons.append("title")
    if p["product_type"] != d["category"]:
        payload["product_type"] = d["category"]; payload["tags"] = d["category"]; reasons.append("category")
    if first_sync or old_h.get("c") != d["hash"]["c"]:
        payload["body_html"] = d["body_html"]
        if "details" not in reasons and not first_sync:
            reasons.append("details")
    # only re-activate products that THIS sync hid earlier (never ones you drafted/archived yourself)
    if p["status"] != "ACTIVE" and old_h.get("d") == "1":
        payload["status"] = "active"; reasons.append("re-activate")

    # images: on first sync only fill in products that have none (avoid re-uploading the whole store)
    if (first_sync and not p["has_image"] and d["images"]) or (not first_sync and old_h.get("i") != d["hash"]["i"]):
        payload["images"] = [{"src": u} for u in d["images"]]; reasons.append("images")

    # variants: compare the set of option values (from SKUs) with the supplier
    want = [val for _, val in d["variants"]]
    have = {}
    for v in p["variants"]:
        sku = v["sku"]
        val = sku[len(d["code"]) + 1:] if sku.startswith(d["code"] + "-") else None
        have[(val or "").lower()] = v
    want_keys = [w.lower() for w in want] if want else [""]
    variants_changed = set(want_keys) != set(have.keys())

    if variants_changed:
        new_vars = []
        if want:
            for val in want:
                ex = have.get(val.lower())
                nv = {"option1": val, "price": str(d["price"]), "compare_at_price": str(d["compare_at"]),
                      "sku": sku_for(d["code"], val), "inventory_management": None}
                if ex:
                    nv["id"] = ex["id"]
                new_vars.append(nv)
            payload["options"] = [{"name": d["option_name"]}]
        else:
            ex = have.get("")
            nv = {"price": str(d["price"]), "compare_at_price": str(d["compare_at"]), "sku": d["code"],
                  "inventory_management": None}
            if ex:
                nv["id"] = ex["id"]
            new_vars.append(nv)
        payload["variants"] = new_vars
        reasons.append("variants")
    else:
        for v in p["variants"]:
            if abs(v["price"] - d["price"]) > 0.01 or abs(v["compare_at"] - d["compare_at"]) > 0.01:
                var_updates.append(v)
        if var_updates:
            reasons.append("price")

    new_hash = encode_hash(d["hash"])
    stored = encode_hash(old_h, drafted_by_sync=old_h.get("d") == "1")
    if old_h.get("d") == "1" and "status" not in payload:
        new_hash = stored  # still hidden (e.g. you archived it meanwhile) - keep the marker
    hash_str = new_hash if new_hash != stored else None
    return (payload or None), var_updates, hash_str, reasons


# ---------------------------------------------------------------- main
def main():
    print(f"Mode: {'DRY RUN (no changes)' if DRY_RUN else 'LIVE'} | min markup x{MIN_MARKUP} | compare-at +{int(COMPARE_AT_PCT*100)}%")
    supplier = fetch_supplier_products()          # raises before any write if incomplete
    shop = Shopify()
    catalog = shop.load_catalog()

    # group Shopify products by supplier code; resolve the (rare) case of 2 products sharing a code
    by_code, extra_copies = {}, []
    for p in catalog:
        codes = {base_code(v["sku"]) for v in p["variants"] if v["sku"]}
        codes.discard("")
        if len(codes) != 1:
            continue  # not a recognisable supplier product, leave it alone
        c = codes.pop()
        if c in by_code:
            keep, other = sorted([by_code[c], p], key=lambda x: x["created_at"])
            by_code[c] = keep
            extra_copies.append(other)
        else:
            by_code[c] = p

    stats = {k: 0 for k in ("created", "updated", "price_only", "unchanged", "drafted", "dup_drafted", "skipped_no_price")}
    reason_counts = {}
    hashes_to_save = []
    samples = []

    def log(line):
        if len(samples) < 40:
            samples.append(line)

    # 1) extra copies of the same supplier code -> draft (never delete)
    for p in extra_copies:
        if p["status"] != "DRAFT":
            stats["dup_drafted"] += 1
            log(f"🗂️  duplicate of code -> draft: {p['title']}")
            if not DRY_RUN:
                shop.update_product(p["id"], {"status": "draft"}, f"draft duplicate {p['title']}")

    # 2) products the supplier no longer lists -> draft
    for c, p in by_code.items():
        if c not in supplier and p["status"] == "ACTIVE":
            stats["drafted"] += 1
            log(f"📦 not at supplier any more -> draft: {p['title']}")
            if not DRY_RUN:
                if shop.update_product(p["id"], {"status": "draft"}, f"draft {p['title']}"):
                    hashes_to_save.append((p["id"], encode_hash(p["hash"], drafted_by_sync=True)))

    # 3) create / update from supplier
    for c, item in supplier.items():
        d = desired_state(item)
        if not d["price"]:
            stats["skipped_no_price"] += 1
            continue
        p = by_code.get(c)
        if p is None:
            stats["created"] += 1
            log(f"✨ new: {d['title']} | Tk {d['price']} (was {d['compare_at']})")
            if not DRY_RUN:
                shop.create_product(d)
                time.sleep(0.5)
            continue

        payload, var_updates, new_hash, reasons = plan_update(p, d)
        for r in reasons:
            reason_counts[r] = reason_counts.get(r, 0) + 1
        if not payload and not var_updates:
            stats["unchanged"] += 1
        elif payload:
            stats["updated"] += 1
            if var_updates:
                # fold price changes into the same product PUT
                payload["variants"] = [{"id": v["id"], "price": str(d["price"]), "compare_at_price": str(d["compare_at"])}
                                       for v in p["variants"]] if "variants" not in payload else payload["variants"]
            old = p["variants"][0]["price"] if p["variants"] else None
            log(f"🔧 {d['title']} [{', '.join(reasons)}] Tk {old} -> {d['price']}")
            if not DRY_RUN:
                shop.update_product(p["id"], payload, f"update {d['title']}")
        else:
            stats["price_only"] += 1
            old = var_updates[0]["price"]
            log(f"💰 {d['title']} Tk {old} -> {d['price']} (was {d['compare_at']})")
            if not DRY_RUN:
                for v in var_updates:
                    shop.update_variant(v["id"], d["price"], d["compare_at"], f"price {d['title']}")
        if new_hash:
            hashes_to_save.append((p["id"], new_hash))

    if not DRY_RUN and hashes_to_save:
        shop.set_hashes(hashes_to_save)

    print("\n--- sample of changes ---")
    for s in samples:
        print(s)
    print("\n--- summary ---")
    for k, v in stats.items():
        print(f"{k:>18}: {v}")
    print(f"{'change reasons':>18}: {reason_counts}")
    print(f"{'write failures':>18}: {shop.write_failures}")

    if shop.write_failures > MAX_WRITE_FAILURES:
        raise SyncAbort(f"{shop.write_failures} Shopify writes failed (limit {MAX_WRITE_FAILURES}).")


if __name__ == "__main__":
    try:
        main()
    except SyncAbort as e:
        print(f"\n❌ SYNC STOPPED: {e}")
        sys.exit(1)
