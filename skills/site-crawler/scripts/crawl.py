#!/usr/bin/env python3
"""Same-domain website crawler for SEO / GEO / AEO audits.

Standard library only. Usage:
    python3 crawl.py https://example.com --max-pages 200 --out crawl_output
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter, defaultdict, deque
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; SiteCrawlerSkill/1.0)"
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip", ".mp4",
            ".mov", ".mp3", ".css", ".js", ".ico", ".xml", ".json", ".woff", ".woff2", ".ttf")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.robots = ""
        self.canonical = ""
        self.h1, self.h2 = [], []
        self.links = []
        self.images = 0
        self.images_no_alt = 0
        self.schema_types = []
        self.lang = ""
        self._in = None
        self._buf = []
        self._in_jsonld = False
        self._jsonld_buf = []
        self._skip = 0
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag in ("title", "h1", "h2"):
            self._in, self._buf = tag, []
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name == "description":
                self.meta_description = a.get("content", "").strip()
            elif name == "robots":
                self.robots = a.get("content", "").strip().lower()
        elif tag == "link" and "canonical" in a.get("rel", "").lower():
            self.canonical = a.get("href", "").strip()
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"].strip())
        elif tag == "img":
            self.images += 1
            if not a.get("alt", "").strip():
                self.images_no_alt += 1
        elif tag == "script":
            if "ld+json" in a.get("type", "").lower():
                self._in_jsonld, self._jsonld_buf = True, []
            else:
                self._skip += 1
        elif tag in ("style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == self._in:
            text = " ".join("".join(self._buf).split())
            if tag == "title":
                self.title = text
            elif tag == "h1":
                self.h1.append(text)
            elif tag == "h2":
                self.h2.append(text)
            self._in = None
        elif tag == "script":
            if self._in_jsonld:
                self._in_jsonld = False
                self._collect_schema("".join(self._jsonld_buf))
            elif self._skip:
                self._skip -= 1
        elif tag in ("style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._in:
            self._buf.append(data)
        if not self._skip:
            self.text_parts.append(data)

    def _collect_schema(self, raw):
        try:
            data = json.loads(raw)
        except Exception:
            return
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, list):
                    self.schema_types.extend(str(x) for x in t)
                elif t:
                    self.schema_types.append(str(t))
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))

    @property
    def word_count(self):
        return len(" ".join(self.text_parts).split())


def normalize(url):
    p = urllib.parse.urlsplit(url)
    path = p.path or "/"
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def host_key(netloc):
    n = netloc.lower().split(":")[0]
    return n[4:] if n.startswith("www.") else n


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(5_000_000)
            ctype = r.headers.get("Content-Type", "")
            charset = r.headers.get_content_charset() or "utf-8"
            return r.status, r.geturl(), ctype, body.decode(charset, "replace"), time.time() - start, r.headers
    except urllib.error.HTTPError as e:
        return e.code, url, e.headers.get("Content-Type", "") if e.headers else "", "", time.time() - start, e.headers
    except Exception as e:
        return 0, url, "", f"ERROR: {e}", time.time() - start, None


def sitemap_urls(base):
    urls = []
    status, _, _, body, _, _ = fetch(urllib.parse.urljoin(base, "/sitemap.xml"))
    if status == 200 and body:
        import re
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", body)
        for loc in locs[:50]:
            if loc.endswith(".xml"):
                s2, _, _, b2, _, _ = fetch(loc)
                if s2 == 200:
                    urls += re.findall(r"<loc>\s*([^<]+?)\s*</loc>", b2)
            else:
                urls.append(loc)
    return urls


def main():
    ap = argparse.ArgumentParser(description="Crawl a site and audit on-page SEO.")
    ap.add_argument("url")
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--ignore-robots", action="store_true")
    ap.add_argument("--out", default="crawl_output")
    args = ap.parse_args()

    start = args.url if "://" in args.url else "https://" + args.url
    start = normalize(start)
    site = host_key(urllib.parse.urlsplit(start).netloc)
    os.makedirs(args.out, exist_ok=True)

    rp = urllib.robotparser.RobotFileParser()
    if not args.ignore_robots:
        try:
            rp.set_url(urllib.parse.urljoin(start, "/robots.txt"))
            rp.read()
        except Exception:
            rp = None
    else:
        rp = None

    def allowed(u):
        if any(x in u for x in args.exclude):
            return False
        if u.lower().split("?")[0].endswith(SKIP_EXT):
            return False
        return rp is None or rp.can_fetch(UA, u)

    queue = deque([start])
    seen = {start}
    for u in sitemap_urls(start):
        n = normalize(u)
        if host_key(urllib.parse.urlsplit(n).netloc) == site and n not in seen:
            seen.add(n)
            queue.append(n)

    pages, inlinks = [], defaultdict(set)
    while queue and len(pages) < args.max_pages:
        url = queue.popleft()
        if not allowed(url):
            continue
        status, final, ctype, body, secs, headers = fetch(url)
        print(f"[{len(pages) + 1}] {status} {url}", file=sys.stderr)
        rec = {"url": url, "final_url": final, "status": status, "load_s": round(secs, 2),
               "title": "", "title_len": 0, "meta_description": "", "meta_len": 0,
               "h1": "", "h1_count": 0, "h2_count": 0, "canonical": "", "robots": "",
               "lang": "", "word_count": 0, "schema_types": "", "images": 0,
               "images_no_alt": 0, "internal_links": [], "external_links": []}
        if headers is not None and "x-robots-tag" in headers:
            rec["robots"] = headers["x-robots-tag"].lower()
        if status == 200 and "html" in ctype.lower():
            p = PageParser()
            try:
                p.feed(body)
            except Exception:
                pass
            rec.update(title=p.title, title_len=len(p.title), meta_description=p.meta_description,
                       meta_len=len(p.meta_description), h1=" | ".join(p.h1), h1_count=len(p.h1),
                       h2_count=len(p.h2), canonical=urllib.parse.urljoin(final, p.canonical) if p.canonical else "",
                       robots=rec["robots"] or p.robots, lang=p.lang, word_count=p.word_count,
                       schema_types=", ".join(sorted(set(p.schema_types))), images=p.images,
                       images_no_alt=p.images_no_alt)
            for href in p.links:
                if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                    continue
                absu = normalize(urllib.parse.urljoin(final, href))
                if not absu.startswith("http"):
                    continue
                if host_key(urllib.parse.urlsplit(absu).netloc) == site:
                    rec["internal_links"].append(absu)
                    inlinks[absu].add(url)
                    if absu not in seen:
                        seen.add(absu)
                        queue.append(absu)
                else:
                    rec["external_links"].append(absu)
        pages.append(rec)
        time.sleep(args.delay)

    # ---- issues ----
    issues = []

    def add(sev, url, issue, detail=""):
        issues.append({"severity": sev, "url": url, "issue": issue, "detail": detail})

    by_status = {p["url"]: p["status"] for p in pages}
    titles = Counter(p["title"] for p in pages if p["title"])
    metas = Counter(p["meta_description"] for p in pages if p["meta_description"])
    for p in pages:
        u, s = p["url"], p["status"]
        if s == 0 or s >= 400:
            add("Critical", u, f"HTTP {s or 'error'}", "linked from: " + ", ".join(sorted(inlinks.get(u, []))[:5]))
            continue
        if s != 200:
            continue
        if "noindex" in p["robots"]:
            add("Critical", u, "noindex set", p["robots"])
        if not p["title"]:
            add("Critical", u, "Missing <title>")
        elif titles[p["title"]] > 1:
            add("Critical", u, "Duplicate title", p["title"])
        elif p["title_len"] > 60:
            add("High", u, "Title over 60 chars", f"{p['title_len']}: {p['title']}")
        if not p["meta_description"]:
            add("High", u, "Missing meta description")
        else:
            if metas[p["meta_description"]] > 1:
                add("High", u, "Duplicate meta description")
            if p["meta_len"] > 160:
                add("High", u, "Meta description over 160 chars", str(p["meta_len"]))
            elif p["meta_len"] < 70:
                add("High", u, "Meta description under 70 chars", str(p["meta_len"]))
        if p["h1_count"] == 0:
            add("High", u, "Missing H1")
        elif p["h1_count"] > 1:
            add("High", u, "Multiple H1s", p["h1"])
        if p["canonical"] and normalize(p["canonical"]) != normalize(p["final_url"]):
            add("High", u, "Canonical points elsewhere", p["canonical"])
        if not p["canonical"]:
            add("Medium", u, "No canonical tag")
        if not p["schema_types"]:
            add("High", u, "No structured data (JSON-LD)")
        if p["word_count"] < 300:
            add("GEO/AEO", u, "Thin content (<300 words)", str(p["word_count"]))
        if p["images_no_alt"]:
            add("Medium", u, "Images missing alt text", f"{p['images_no_alt']} of {p['images']}")
        if p["load_s"] > 2:
            add("Low", u, "Slow response (>2s)", f"{p['load_s']}s")
        for link in set(p["internal_links"]):
            if by_status.get(link, 200) >= 400 or by_status.get(link) == 0:
                add("Critical", u, "Links to broken page", link)
        if p["url"] != start and len(inlinks.get(u, ())) <= 1:
            add("Low", u, "Few internal links pointing here", str(len(inlinks.get(u, ()))))

    # ---- write outputs ----
    cols = ["url", "final_url", "status", "load_s", "title", "title_len", "meta_description", "meta_len",
            "h1", "h1_count", "h2_count", "canonical", "robots", "lang", "word_count", "schema_types",
            "images", "images_no_alt", "internal_link_count", "external_link_count", "inlinks"]
    with open(os.path.join(args.out, "pages.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in pages:
            row = {k: p.get(k, "") for k in cols}
            row["internal_link_count"] = len(set(p["internal_links"]))
            row["external_link_count"] = len(set(p["external_links"]))
            row["inlinks"] = len(inlinks.get(p["url"], ()))
            w.writerow(row)
    with open(os.path.join(args.out, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f, indent=2)
    with open(os.path.join(args.out, "issues.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["severity", "url", "issue", "detail"])
        w.writeheader()
        order = {"Critical": 0, "High": 1, "GEO/AEO": 2, "Medium": 3, "Low": 4}
        w.writerows(sorted(issues, key=lambda i: order.get(i["severity"], 9)))

    sev = Counter(i["severity"] for i in issues)
    top = Counter(i["issue"] for i in issues).most_common(10)
    statuses = Counter(p["status"] for p in pages)
    lines = [f"# Crawl summary: {start}", "",
             f"- Pages crawled: {len(pages)} (limit {args.max_pages})",
             f"- Status codes: " + ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())),
             f"- Issues: " + ", ".join(f"{k}: {sev[k]}" for k in ["Critical", "High", "GEO/AEO", "Medium", "Low"] if sev[k]),
             "", "## Top issues", ""]
    lines += [f"- {name}: {count} pages" for name, count in top]
    ok_pages = [p for p in pages if p["status"] == 200]
    if ok_pages and all(p["word_count"] < 50 for p in ok_pages):
        lines += ["", "> Most pages have almost no text in raw HTML. The site may render content with JavaScript; check pages in a browser."]
    with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Done: {len(pages)} pages, {len(issues)} issues -> {args.out}/", file=sys.stderr)


if __name__ == "__main__":
    main()
