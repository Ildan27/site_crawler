---
name: site-crawler
description: Crawl a website and audit every page for SEO, GEO and AEO issues (titles, meta descriptions, headings, canonicals, schema, broken links, missing alt text). Use when asked to crawl, audit or map a site.
---

# Site Crawler

Crawls one website (same domain only), collects on-page SEO data for every page it finds, and turns it into a clear audit with prioritized fixes.

## When to use

- "Crawl / audit / map this site"
- "Check this website's SEO" or "is this site ready for AI search (GEO/AEO)?"
- "Find broken links / missing meta descriptions / missing alt text"
- Before and after a website rebrand or migration, to compare

## Step 1 — Get the inputs

Ask only for what is missing:
- **Start URL** (required), e.g. `https://example.com`
- **Page limit** (default 200)
- Optional: paths to skip (e.g. `/blog/tag/`), or a focus (local SEO, listings pages, blog)

## Step 2 — Run the crawler

The script uses only the Python standard library, so nothing needs installing.

```bash
python3 scripts/crawl.py https://example.com --max-pages 200 --out crawl_output
```

Options:
- `--max-pages N` — stop after N pages (default 200)
- `--delay SECONDS` — pause between requests (default 0.5; be polite)
- `--exclude PATTERN` — skip URLs containing this text (repeatable)
- `--ignore-robots` — only if the site owner asked for it

It writes to the output folder:
- `pages.csv` — one row per page (status, title, meta description, H1s, canonical, word count, schema types, image/alt counts, load time)
- `pages.json` — the same data plus every link found
- `issues.csv` — one row per issue, with severity
- `summary.md` — counts and the top problems

If the network is blocked in the current environment, say so plainly and ask the user to run the script on their own computer, then upload the output folder.

## Step 3 — Analyze

Read `summary.md` and `issues.csv`, then check `pages.csv` for patterns. Look for:

**Critical**
- Pages returning 4xx/5xx, and internal links pointing to them
- Pages with `noindex` that should rank
- Missing or duplicate `<title>`

**High**
- Missing or duplicate meta descriptions
- Missing H1, or multiple H1s
- Title over 60 characters, meta description over 160 or under 70
- Canonical pointing to a different URL than expected
- No structured data (JSON-LD) on key pages

**GEO / AEO (AI search readiness)**
- Thin pages (under ~300 words) that should answer questions
- No FAQ, Organization, LocalBusiness, RealEstateAgent, or Article schema where it fits
- Headings that aren't phrased the way people ask questions
- No clear entity info (name, address, phone, service area) on the home and contact pages

**Medium / Low**
- Images missing alt text
- Slow pages (over ~2 s response)
- Orphan-looking pages (found in sitemap/links only once)

## Step 4 — Deliver

Give the user:
1. A one-paragraph verdict on the site's health
2. The top 5–10 fixes, ordered by impact, each with the affected URLs and the exact change to make (e.g. a rewritten title tag)
3. The `pages.csv` and `issues.csv` files for their records

Write new titles and meta descriptions ready to paste, within character limits. Don't pad the report; lead with what to fix first.

## Notes

- Stays on the starting domain (and its `www` variant). Doesn't follow external links, but records them.
- Respects `robots.txt` by default.
- JavaScript-rendered content (some Wix/Squarespace sections) may not appear in the raw HTML. If pages look empty, mention it and suggest checking them in a browser.
