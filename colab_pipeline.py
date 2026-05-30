# ============================================================
# AI & Automation Hackathon — Subtask 1: Research Pipeline
# Company Enrichment via Smart Scraping + Claude AI
# ============================================================
# HOW TO USE:
#   1. Run Cell 1 to install dependencies
#   2. Run Cell 2 to set your Anthropic API key
#   3. Run Cell 3 (all helpers) — no interaction needed
#   4. Run Cell 4 — it will prompt you to paste URLs, then prints JSON
# ============================================================

# ─────────────────────────────────────────────────────────────
# CELL 1 — Install Dependencies
# ─────────────────────────────────────────────────────────────
# !pip install -q anthropic requests beautifulsoup4 lxml

# ─────────────────────────────────────────────────────────────
# CELL 2 — Set API Key
# ─────────────────────────────────────────────────────────────
# import os
# os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."   # <-- paste your key here

# ─────────────────────────────────────────────────────────────
# CELL 3 — All Helper Functions (run this cell first)
# ─────────────────────────────────────────────────────────────

import os, json, time, re, ast
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import anthropic

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TARGET_KEYWORDS = [
    "about", "contact", "services", "service", "solutions",
    "team", "company", "who-we-are", "what-we-do", "our-work",
    "products", "offerings", "expertise", "capabilities"
]


def fetch_page(url, timeout=12):
    """Fetch URL with retry. Returns HTML string or empty string."""
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            time.sleep(1.5)
    return ""


def clean_html(html):
    """
    Strip HTML to clean readable text.
    Removes: script, style, nav, footer, header, cookie banners, modals.
    Deduplicates consecutive identical lines.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "noscript", "iframe", "svg", "form", "aside",
                     "meta", "link", "button"]):
        tag.decompose()
    # Remove cookie/popup overlays
    for tag in soup.find_all(True):
        cls = " ".join(tag.get("class", []))
        if any(kw in cls.lower() for kw in ["cookie", "banner", "popup", "modal", "overlay", "ads"]):
            tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    deduped, prev = [], None
    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line
    return "\n".join(deduped)


def get_sitemap_urls(base_url):
    """Try /sitemap.xml and /sitemap_index.xml for all URLs."""
    urls = []
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/"]:
        try:
            resp = requests.get(base_url.rstrip("/") + path, headers=HEADERS, timeout=8)
            if resp.status_code == 200 and "<url>" in resp.text.lower():
                soup = BeautifulSoup(resp.text, "xml")
                locs = soup.find_all("loc")
                urls = [l.get_text().strip() for l in locs]
                if urls:
                    break
        except Exception:
            continue
    return urls


def fuzzy_match_links(links, keywords=TARGET_KEYWORDS):
    """Return only links whose path contains at least one target keyword."""
    matched = []
    for link in links:
        path = urlparse(link).path.lower()
        if any(kw in path for kw in keywords):
            matched.append(link)
    return matched


def get_relevant_links_from_html(base_url, html):
    """Extract all internal links from page HTML, then fuzzy-match."""
    soup = BeautifulSoup(html, "html.parser")
    base = urlparse(base_url)
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.netloc == base.netloc and parsed.scheme in ("http", "https"):
            links.add(full)
    return fuzzy_match_links(list(links))


def scrape_company(url):
    """
    Multi-approach scraping pipeline:
      Approach 1 — Fetch homepage directly
      Approach 2 — Try sitemap.xml for structured URL list
      Approach 3 — Extract + fuzzy-match links from homepage HTML
    Returns combined, token-optimised text (~4000 words max).
    """
    base_url = url.rstrip("/")
    combined_text = []

    # Approach 1: Homepage
    print(f"  [1] Fetching homepage: {base_url}")
    homepage_html = fetch_page(base_url)
    if homepage_html:
        combined_text.append("=== HOMEPAGE ===\n" + clean_html(homepage_html))
    else:
        print("  [!] Homepage fetch failed — site may be blocking crawlers.")

    # Approach 2: Sitemap
    print(f"  [2] Trying sitemap...")
    sitemap_urls = get_sitemap_urls(base_url)
    relevant_sitemap = fuzzy_match_links(sitemap_urls)[:4]

    # Approach 3: Link extraction from homepage HTML
    print(f"  [3] Extracting links from homepage HTML...")
    relevant_inline = get_relevant_links_from_html(base_url, homepage_html)[:4] if homepage_html else []

    all_relevant = list(dict.fromkeys(relevant_sitemap + relevant_inline))[:5]
    print(f"  [→] Relevant sub-pages to scrape: {len(all_relevant)}")

    for link in all_relevant:
        if link == base_url:
            continue
        time.sleep(0.6)  # polite delay
        html = fetch_page(link)
        if html:
            section = urlparse(link).path.strip("/").replace("/", " > ") or "page"
            combined_text.append(f"=== {section.upper()} ===\n" + clean_html(html))

    full_text = "\n\n".join(combined_text)

    # Token optimisation: cap at ~4000 words ≈ 5500 tokens
    words = full_text.split()
    if len(words) > 4000:
        full_text = " ".join(words[:4000])
        print(f"  [!] Text truncated to 4000 words for token efficiency.")

    return full_text


def enrich_with_ai(url, scraped_text):
    """
    Call Claude to extract a structured JSON company profile.
    Anti-hallucination: model is instructed to return N/A for missing fields.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_prompt = """You are a precise business intelligence extractor.
Your ONLY job is to extract factual information from the provided website text.

CRITICAL RULES:
- NEVER hallucinate or invent contact details, emails, phone numbers, or services.
- If a field is NOT found in the text, return "" or "N/A" — never guess or fabricate.
- Emails MUST contain the @ symbol and be genuinely found in the text.
- Phone numbers MUST be actual numbers found in the text.
- Return ONLY valid JSON. No markdown code fences, no explanation, no extra text.
"""

    user_prompt = f"""Extract company information from the website content below.
URL: {url}

WEBSITE CONTENT:
{scraped_text}

Return a single JSON object with EXACTLY these fields:
{{
  "website_name": "Short brand name",
  "company_name": "Full legal or trade name",
  "address": "Physical address if found, else N/A",
  "mobile_number": "Phone number if found in text, else N/A",
  "mail": ["list of email addresses actually found in the text"],
  "core_service": "Primary service or product in one clear sentence",
  "target_customer": "Who they sell to — industry, company size, persona",
  "probable_pain_point": "The core business problem their customers face",
  "outreach_opener": "A personalised 2-sentence cold outreach opening mentioning the company name and their specific service"
}}

IMPORTANT: Only use information present in the provided website content.
Return pure JSON only — no markdown, no explanation."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw = message.content[0].text.strip()
    # Defensive: strip markdown code fences if model added them
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$", "", raw.strip()).strip()

    data = json.loads(raw)

    # Schema stability — guarantee all keys always exist
    defaults = {
        "website_name": "N/A",
        "company_name": "N/A",
        "address": "N/A",
        "mobile_number": "N/A",
        "mail": [],
        "core_service": "N/A",
        "target_customer": "N/A",
        "probable_pain_point": "N/A",
        "outreach_opener": "N/A"
    }
    for key, default in defaults.items():
        if key not in data or data[key] is None:
            data[key] = default
    if not isinstance(data["mail"], list):
        data["mail"] = [data["mail"]] if data["mail"] and data["mail"] != "N/A" else []

    return data


def process_urls(urls):
    """
    Main pipeline: takes a list of URLs, returns list of enriched JSON objects.
    This is the required function structure for the hackathon.
    """
    results = []
    for i, url in enumerate(urls):
        print(f"\n[{i+1}/{len(urls)}] Processing: {url}")
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
        try:
            scraped = scrape_company(url)
            if not scraped:
                print(f"  [ERROR] Could not scrape {url}. Returning N/A profile.")
                result = {
                    "website_name": "N/A", "company_name": "N/A",
                    "address": "N/A", "mobile_number": "N/A", "mail": [],
                    "core_service": "N/A", "target_customer": "N/A",
                    "probable_pain_point": "N/A", "outreach_opener": "N/A"
                }
            else:
                result = enrich_with_ai(url, scraped)
            result["source_url"] = url
            results.append(result)
            print(f"  [✓] Done: {result.get('company_name', 'N/A')}")
        except Exception as e:
            print(f"  [ERROR] {e}")
            results.append({
                "website_name": "N/A", "company_name": "N/A",
                "address": "N/A", "mobile_number": "N/A", "mail": [],
                "core_service": "N/A", "target_customer": "N/A",
                "probable_pain_point": "N/A", "outreach_opener": "N/A",
                "source_url": url, "error": str(e)
            })
        time.sleep(1)  # polite delay between companies
    return results


print("✅ All helper functions loaded. Run the next cell to start.")


# ─────────────────────────────────────────────────────────────
# CELL 4 — Main Entry Point (run this, paste your URLs when prompted)
# ─────────────────────────────────────────────────────────────

print("=" * 60)
print("  COMPANY ENRICHMENT PIPELINE")
print("=" * 60)
print("Paste your URL array below (JSON format), e.g.:")
print('  ["https://stripe.com", "https://shopify.com"]')
print("Then press Enter twice.\n")

raw_input_str = input("Enter URL array: ").strip()

try:
    urls = json.loads(raw_input_str)
    if not isinstance(urls, list):
        raise ValueError("Input must be a JSON array")
except json.JSONDecodeError:
    # Try Python literal eval as fallback
    try:
        urls = ast.literal_eval(raw_input_str)
    except Exception:
        raise ValueError("Could not parse input. Make sure it's a valid JSON array like: [\"url1\", \"url2\"]")

print(f"\n🚀 Starting enrichment for {len(urls)} URL(s)...\n")
results = process_urls(urls)

# Save results.json
with open("results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\n" + "=" * 60)
print("✅ ENRICHMENT COMPLETE")
print("=" * 60)
print(f"Processed: {len(results)} companies")
print("Saved to: results.json")
print("\n📤 OUTPUT JSON:\n")
print(json.dumps(results, indent=2))
